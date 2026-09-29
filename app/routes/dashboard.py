import hmac

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.services.aluguer_service import AluguerService
from app.services.contentor_service import ContentorService
from app.services.reminder_service import ReminderService



def _dashboard_autorizado(x_dashboard_token: str | None = Header(default=None)) -> None:
    """Os endpoints devolvem dados de clientes (nome, telefone): exigem token.

    Sem DASHBOARD_TOKEN no .env os endpoints ficam desligados (404).
    """
    esperado = get_settings().dashboard_token.strip()
    if not esperado:
        raise HTTPException(status_code=404, detail="Not Found")
    recebido = (x_dashboard_token or "").encode("utf-8")
    if not hmac.compare_digest(recebido, esperado.encode("utf-8")):
        raise HTTPException(status_code=401, detail="Invalid dashboard token")


router = APIRouter(
    prefix="/dashboard",
    tags=["dashboard"],
    dependencies=[Depends(_dashboard_autorizado)],
)


@router.get("/contentores")
def listar_contentores(db: Session = Depends(get_db)) -> list[dict]:
    return [
        {"id": contentor.id, "codigo": contentor.codigo, "status": contentor.status.value}
        for contentor in ContentorService(db).listar_contentores()
    ]


@router.get("/alugueres/vencendo-amanha")
def listar_vencendo_amanha(db: Session = Depends(get_db)) -> list[dict]:
    return [
        {
            "id": aluguer.id,
            "cliente": aluguer.nome_cliente,
            "telefone": aluguer.telefone_cliente,
            "data_vencimento": aluguer.data_vencimento.isoformat(),
            "status": aluguer.status.value,
        }
        for aluguer in AluguerService(db).listar_vencendo_amanha()
    ]


@router.get("/lembretes")
def listar_lembretes(db: Session = Depends(get_db)) -> dict[str, list[str]]:
    return {"mensagens": ReminderService(db).mensagens_vencendo_amanha()}
