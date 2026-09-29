import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.routes import webhook

APP_SECRET = "segredo-de-teste"


class RouterEco:
    calls = []

    def __init__(self, db):
        self.db = db

    def handle(self, message):
        type(self).calls.append(message.texto)
        return "resposta"

    def pop_pending_messages(self):
        return []


@pytest.fixture
def envios(monkeypatch):
    RouterEco.calls = []
    registrados = []
    monkeypatch.setattr(webhook, "WhatsappRouterAgent", RouterEco)
    monkeypatch.setattr(
        webhook,
        "send_whatsapp_message",
        lambda telefone, corpo, force_mock=False: registrados.append((telefone, corpo, force_mock))
        or {"status": "mocked"},
    )
    return registrados


@pytest.fixture
def com_app_secret(monkeypatch):
    monkeypatch.setenv("WHATSAPP_APP_SECRET", APP_SECRET)
    get_settings.cache_clear()
    yield
    monkeypatch.delenv("WHATSAPP_APP_SECRET")
    get_settings.cache_clear()


def _corpo(message_id="wamid.assinatura", texto="menu"):
    payload = {
        "entry": [{"changes": [{"value": {"messages": [
            {"from": "351900000000", "id": message_id, "type": "text", "text": {"body": texto}}
        ]}}]}]
    }
    return json.dumps(payload).encode("utf-8")


def _assinar(corpo, segredo=APP_SECRET):
    return "sha256=" + hmac.new(segredo.encode("utf-8"), corpo, hashlib.sha256).hexdigest()


def _post(client, corpo, **headers):
    return TestClient(client).post(
        "/webhook/whatsapp",
        content=corpo,
        headers={"content-type": "application/json", **headers},
    )


def test_com_app_secret_aceita_payload_assinado_pela_meta(client, envios, com_app_secret):
    corpo = _corpo()

    response = _post(client, corpo, **{"X-Hub-Signature-256": _assinar(corpo)})

    assert response.status_code == 200
    assert RouterEco.calls == ["menu"]
    assert envios == [("351900000000", "resposta", False)]


@pytest.mark.parametrize(
    "assinatura",
    [None, "", "sha256=", "sha256=00", "md5=abc", "sha256=" + "F" * 64],
)
def test_com_app_secret_rejeita_payload_sem_assinatura_valida(client, envios, com_app_secret, assinatura):
    headers = {} if assinatura is None else {"X-Hub-Signature-256": assinatura}

    response = _post(client, _corpo(), **headers)

    assert response.status_code == 401
    assert RouterEco.calls == []
    assert envios == []


def test_com_app_secret_rejeita_assinatura_de_outro_segredo_ou_corpo_alterado(client, envios, com_app_secret):
    original = _corpo(texto="menu")
    adulterado = _corpo(texto="registrar pagamento")

    outro_segredo = _post(client, original, **{"X-Hub-Signature-256": _assinar(original, "outro")})
    corpo_trocado = _post(client, adulterado, **{"X-Hub-Signature-256": _assinar(original)})

    assert outro_segredo.status_code == corpo_trocado.status_code == 401
    assert RouterEco.calls == []


def test_com_app_secret_cabecalho_de_mock_nao_silencia_respostas(client, envios, com_app_secret):
    corpo = _corpo()

    _post(client, corpo, **{"X-Hub-Signature-256": _assinar(corpo), "X-OLT-Mock-Whatsapp": "true"})

    assert envios == [("351900000000", "resposta", False)]


def test_sem_app_secret_mantem_compatibilidade_e_cabecalho_de_mock(client, envios, monkeypatch):
    monkeypatch.delenv("WHATSAPP_APP_SECRET", raising=False)
    get_settings.cache_clear()

    response = _post(client, _corpo(), **{"X-OLT-Mock-Whatsapp": "true"})

    assert response.status_code == 200
    assert envios == [("351900000000", "resposta", True)]


def test_producao_sem_app_secret_rejeita_webhook(client, envios, monkeypatch):
    monkeypatch.setattr(webhook, "get_settings", lambda: Settings(env="production"))

    response = _post(client, _corpo(), **{"X-OLT-Mock-Whatsapp": "true"})

    assert response.status_code == 503
    assert RouterEco.calls == []
    assert envios == []


@pytest.mark.parametrize("environment", ["prod", "production"])
def test_producao_sem_app_secret_impede_inicializacao(monkeypatch, environment):
    from app import main

    monkeypatch.setattr(main, "get_settings", lambda: Settings(env=environment, whatsapp_app_secret="   "))

    with pytest.raises(RuntimeError, match="WHATSAPP_APP_SECRET"):
        main.create_app()


def test_falha_no_roteador_avisa_o_operador_em_vez_de_silencio(client, envios, monkeypatch):
    class RouterQuebrado(RouterEco):
        def handle(self, message):
            raise RuntimeError("falha interna")

    monkeypatch.setattr(webhook, "WhatsappRouterAgent", RouterQuebrado)

    response = _post(client, _corpo(message_id="wamid.falha"))

    assert response.status_code == 200
    assert response.json()["failed"] == 1
    assert envios == [("351900000000", webhook.ROUTER_FAILURE_MESSAGE, False)]
