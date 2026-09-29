import hashlib
import hmac
import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.agents.whatsapp_router_agent import WhatsappRouterAgent
from app.core.config import get_settings, require_whatsapp_app_secret_in_production
from app.core.db import get_db
from app.integrations.whatsapp.client import send_whatsapp_message
from app.integrations.whatsapp.parser import parse_whatsapp_payload
from app.services.webhook_dedup_service import WebhookDedupService
from app.services.whatsapp_phone_queue_service import WhatsAppPhoneQueueService

router = APIRouter(prefix="/webhook", tags=["webhook"])
logger = logging.getLogger(__name__)

ROUTER_FAILURE_MESSAGE = (
    "⚠️ Não foi possível processar a sua mensagem agora. "
    "Tente novamente ou envie menu para recomeçar."
)
_aviso_assinatura_emitido = False


def _before_send() -> None:
    """Fronteira explícita entre o processamento inbound e o envio outbound."""


async def _assinatura_meta_validada(request: Request) -> bool:
    """Valida X-Hub-Signature-256 quando WHATSAPP_APP_SECRET está configurado.

    Sem o segredo, o endpoint mantém o comportamento anterior e aceita
    qualquer POST: nesse modo, quem conhece a URL pode se passar por um
    operador autorizado apenas informando o telefone no payload.
    """
    global _aviso_assinatura_emitido
    settings = get_settings()
    try:
        require_whatsapp_app_secret_in_production(settings)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Webhook signature verification unavailable") from exc
    app_secret = settings.whatsapp_app_secret.strip()
    if not app_secret:
        if not _aviso_assinatura_emitido:
            logger.warning("WHATSAPP_APP_SECRET ausente: assinatura da Meta não é verificada")
            _aviso_assinatura_emitido = True
        return False
    esperado = "sha256=" + hmac.new(
        app_secret.encode("utf-8"), await request.body(), hashlib.sha256
    ).hexdigest()
    recebido = request.headers.get("x-hub-signature-256", "")
    if not hmac.compare_digest(esperado.encode("utf-8"), recebido.encode("utf-8")):
        raise HTTPException(status_code=401, detail="Invalid signature")
    return True


def _avisar_falha(telefone: str, force_mock: bool, log_key: str) -> None:
    try:
        send_whatsapp_message(telefone, ROUTER_FAILURE_MESSAGE, force_mock=force_mock)
    except Exception as exc:
        logger.error("Webhook failure notice send failed key=%s error=%s", log_key, type(exc).__name__)


@router.get("/whatsapp", response_class=PlainTextResponse)
def verify_whatsapp_webhook(
    hub_mode: str = Query(alias="hub.mode"),
    hub_verify_token: str = Query(alias="hub.verify_token"),
    hub_challenge: str = Query(alias="hub.challenge"),
) -> str:
    settings = get_settings()
    if hub_mode == "subscribe" and hub_verify_token == settings.whatsapp_verify_token:
        return hub_challenge
    raise HTTPException(status_code=403, detail="Invalid verify token")


@router.post("/whatsapp")
def receive_whatsapp_webhook(
    payload: dict,
    db: Session = Depends(get_db),
    x_olt_mock_whatsapp: str | None = Header(default=None),
    assinatura_validada: bool = Depends(_assinatura_meta_validada),
) -> dict:
    processed = 0
    ignored = 0
    failed = 0
    # O cabeçalho de mock existe para os scripts locais; com a assinatura
    # ativa ele seria só um meio de silenciar as respostas ao operador real.
    force_mock = not assinatura_validada and (
        (x_olt_mock_whatsapp or "").strip().lower() in {"1", "true", "yes", "sim"}
    )
    messages = parse_whatsapp_payload(payload)
    for message in messages:
        dedup = WebhookDedupService(db)
        log_key = dedup.log_key(message.message_id)
        try:
            decision = dedup.adquirir(message)
        except Exception as exc:
            db.rollback()
            logger.error("Webhook claim failed key=%s error=%s", log_key, type(exc).__name__)
            raise HTTPException(status_code=503, detail="Webhook temporarily unavailable") from None

        if not decision.deve_processar:
            logger.info("Webhook ignored key=%s reason=%s", log_key, decision.motivo_interno)
            ignored += 1
            continue

        registro = decision.registro
        if registro is None:
            logger.error("Webhook claim missing key=%s", log_key)
            raise HTTPException(status_code=503, detail="Webhook temporarily unavailable")

        # Mensagens do mesmo telefone chegam em POSTs concorrentes (ex.: várias
        # fotos de uma vez). A fila serializa o processamento por telefone para
        # que duas mensagens não leiam e gravem o mesmo contexto da conversa.
        fila = WhatsAppPhoneQueueService(db)
        try:
            vez = fila.wait_turn(fila.enqueue(message.telefone, message.message_id))
        except Exception as exc:
            db.rollback()
            try:
                dedup.marcar_falhou_reprocessavel(registro, exc)
            except Exception as mark_exc:
                db.rollback()
                logger.error("Webhook retryable mark failed key=%s error=%s", log_key, type(mark_exc).__name__)
            logger.error("Webhook phone queue unavailable key=%s error=%s", log_key, type(exc).__name__)
            raise HTTPException(status_code=503, detail="Webhook temporarily unavailable") from None

        sucesso = False
        try:
            processed_msg, failed_msg = _processar_na_vez(db, dedup, registro, message, force_mock, log_key)
            sucesso = failed_msg == 0
        finally:
            liberar = fila.complete if sucesso else fila.fail
            if not liberar(vez.queue_id, vez.owner_token):
                logger.warning("Webhook phone queue turn already released key=%s", log_key)
        processed += processed_msg
        failed += failed_msg
    if not messages:
        return {"status": "ok", "messages": []}
    return {"status": "ok", "processed": processed, "ignored": ignored, "failed": failed}


def _processar_na_vez(db, dedup, registro, message, force_mock: bool, log_key: str) -> tuple[int, int]:
    """Processa uma mensagem já deduplicada; devolve (processadas, falhas)."""
    try:
        router_agent = WhatsappRouterAgent(db)
    except Exception as exc:
        db.rollback()
        try:
            dedup.marcar_falhou_reprocessavel(registro, exc)
        except Exception as mark_exc:
            db.rollback()
            logger.error("Webhook retryable mark failed key=%s error=%s", log_key, type(mark_exc).__name__)
        logger.error("Webhook failed before router key=%s error=%s", log_key, type(exc).__name__)
        raise HTTPException(status_code=503, detail="Webhook temporarily unavailable") from None

    try:
        response = router_agent.handle(message)
    except Exception as exc:
        db.rollback()
        try:
            dedup.marcar_falhou_definitiva(registro, exc)
        except Exception as mark_exc:
            db.rollback()
            logger.error("Webhook definitive mark failed key=%s error=%s", log_key, type(mark_exc).__name__)
        logger.error("Webhook router failed key=%s error=%s", log_key, type(exc).__name__)
        _avisar_falha(message.telefone, force_mock, log_key)
        return 0, 1

    try:
        _before_send()
    except Exception as exc:
        db.rollback()
        try:
            dedup.marcar_falhou_definitiva(registro, exc)
        except Exception as mark_exc:
            db.rollback()
            logger.error("Webhook definitive mark failed key=%s error=%s", log_key, type(mark_exc).__name__)
        logger.error("Webhook failed before sender key=%s error=%s", log_key, type(exc).__name__)
        return 0, 1

    resposta_enviada = True
    try:
        result = send_whatsapp_message(message.telefone, response, force_mock=force_mock)
        resposta_enviada = result.get("status") != "error"
        for pending in router_agent.pop_pending_messages():
            pending_result = send_whatsapp_message(message.telefone, pending, force_mock=force_mock)
            resposta_enviada = resposta_enviada and pending_result.get("status") != "error"
    except Exception as exc:
        resposta_enviada = False
        logger.error("Webhook response send failed key=%s error=%s", log_key, type(exc).__name__)

    failed = 0 if resposta_enviada else 1

    try:
        dedup.marcar_concluida(registro, resposta_enviada)
    except Exception as exc:
        db.rollback()
        logger.error("Webhook completion mark failed key=%s error=%s", log_key, type(exc).__name__)
        failed = 1
    return 1, failed
