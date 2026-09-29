"""Os endpoints /dashboard/* devolvem nome e telefone de clientes (RGPD)."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.time import utcnow
from app.services.aluguer_service import AluguerService
from app.services.seed_service import SeedService

ENDPOINTS = [
    "/dashboard/contentores",
    "/dashboard/alugueres/vencendo-amanha",
    "/dashboard/lembretes",
]


@pytest.fixture()
def dashboard_token(monkeypatch):
    def configurar(valor):
        monkeypatch.setenv("DASHBOARD_TOKEN", valor)
        get_settings.cache_clear()

    yield configurar
    get_settings.cache_clear()


@pytest.mark.parametrize("url", ENDPOINTS)
def test_sem_token_configurado_endpoints_ficam_desligados(client, dashboard_token, url):
    dashboard_token("")

    response = TestClient(client).get(url, headers={"X-Dashboard-Token": "qualquer"})

    assert response.status_code == 404


@pytest.mark.parametrize("url", ENDPOINTS)
@pytest.mark.parametrize("cabecalho", [None, "errado"])
def test_token_ausente_ou_errado_recebe_401(client, dashboard_token, url, cabecalho):
    dashboard_token("segredo-do-painel")
    headers = {"X-Dashboard-Token": cabecalho} if cabecalho else {}

    response = TestClient(client).get(url, headers=headers)

    assert response.status_code == 401


def test_token_certo_devolve_dados(client, db_session, dashboard_token):
    dashboard_token("segredo-do-painel")
    SeedService(db_session).seed_contentores_iniciais()
    aluguer = AluguerService(db_session).registrar_novo_aluguer(
        nome_cliente="Cliente Painel",
        telefone_cliente="351900000321",
        valor="100",
        forma_pagamento="dinheiro",
        pago=True,
    )
    aluguer.data_vencimento = utcnow() + timedelta(days=1)
    db_session.commit()
    headers = {"X-Dashboard-Token": "segredo-do-painel"}
    api = TestClient(client)

    contentores = api.get("/dashboard/contentores", headers=headers)
    vencendo = api.get("/dashboard/alugueres/vencendo-amanha", headers=headers)

    assert contentores.status_code == 200
    assert len(contentores.json()) == 20
    assert vencendo.status_code == 200
