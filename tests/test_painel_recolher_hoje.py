from datetime import timedelta

import pytest

from app.agents.whatsapp_router_agent import WhatsappRouterAgent
from app.core.config import get_settings
from app.core.time import utcnow
from app.integrations.whatsapp.parser import NormalizedWhatsAppMessage
from app.models.operador import Operador, PerfilOperador
from app.services.pedido_service import PedidoService

TELEFONE = "351910000001"


@pytest.fixture(autouse=True)
def settings_limpos():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _pedido_entregue_ha(service, nome, adesivo, dias):
    pedido = service.criar(
        nome_cliente=nome,
        telefone_cliente="351912345678",
        data_planejada=utcnow() - timedelta(days=dias),
        valor_global="100",
        pago=True,
        forma_pagamento="MBWay",
        pedido_feito_por="gestor",
        endereco_aproximado="Rua da Obra",
        ponto_referencia=None,
        residuos=["Entulho Limpo"],
    )
    item = pedido.contentores[0]
    service.confirmar_entrega_lote(
        pedido.id, "motorista", 38.7, -9.1, None,
        [{"contentor_id": item.id, "numero_adesivo": adesivo, "fotos": ["foto"]}],
    )
    item.entrega_data_hora = utcnow() - timedelta(days=dias)
    service.db.commit()


def _secao(painel, titulo):
    inicio = painel.index(titulo)
    fim = painel.find("\n\n", inicio)
    return painel[inicio:fim if fim != -1 else None]


@pytest.mark.parametrize("perfil", [PerfilOperador.GESTOR, PerfilOperador.FUNCIONARIO])
def test_painel_mostra_contentor_cujo_prazo_termina_hoje(db_session, perfil):
    service = PedidoService(db_session)
    _pedido_entregue_ha(service, "Venceu Ontem", "11", 6)
    _pedido_entregue_ha(service, "Vence Hoje", "12", 5)
    _pedido_entregue_ha(service, "Vence Amanha", "13", 4)
    db_session.add(Operador(telefone_whatsapp=TELEFONE, nome_operador="Op", perfil=perfil, ativo=True))
    db_session.commit()

    painel = WhatsappRouterAgent(db_session).handle(
        NormalizedWhatsAppMessage(telefone=TELEFONE, tipo="text", texto="5", message_id="m")
    )

    recolher_hoje = _secao(painel, "Recolher Hoje")
    assert "• Vence Hoje (1 un)" in recolher_hoje
    assert "Nºs: 12" in recolher_hoje
    assert "Rota: https://www.google.com/maps?q=38.7,-9.1" in recolher_hoje
    assert "Venceu Ontem" not in recolher_hoje
    assert "Vence Amanha" not in recolher_hoje
    assert "Venceu Ontem" in _secao(painel, "Contentores com Prazo Vencido")
    assert "Vence Amanha" in _secao(painel, "Recolher Amanhã")


def test_painel_sem_prazo_terminando_hoje_nao_mostra_secao(db_session):
    service = PedidoService(db_session)
    _pedido_entregue_ha(service, "Vence Amanha", "13", 4)
    db_session.add(
        Operador(telefone_whatsapp=TELEFONE, nome_operador="Op", perfil=PerfilOperador.GESTOR, ativo=True)
    )
    db_session.commit()

    painel = WhatsappRouterAgent(db_session).handle(
        NormalizedWhatsAppMessage(telefone=TELEFONE, tipo="text", texto="5", message_id="m")
    )

    assert "Recolher Hoje" not in painel
