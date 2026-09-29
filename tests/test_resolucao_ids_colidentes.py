"""pedido_contentores e alugueres_contentor numeram IDs de forma independente.

O painel oferece "resolver carga <id>" e "resolver avaria <id>" para os dois
modelos, então o mesmo número pode apontar para registros diferentes.
"""
from datetime import datetime, timezone

import pytest

from app.agents.whatsapp_router_agent import WhatsappRouterAgent
from app.core.config import get_settings
from app.integrations.whatsapp.parser import NormalizedWhatsAppMessage
from app.models.aluguer import AluguerContentor, EventoAluguer, StatusResolucao
from app.models.operador import Operador, PerfilOperador
from app.models.pedido import PedidoContentor
from app.services.aluguer_service import AluguerService
from app.services.pedido_service import PedidoService
from app.services.seed_service import SeedService

GESTOR = "351910000001"


@pytest.fixture(autouse=True)
def gestor(db_session):
    get_settings.cache_clear()
    db_session.add(
        Operador(telefone_whatsapp=GESTOR, nome_operador="Gestor", perfil=PerfilOperador.GESTOR, ativo=True)
    )
    db_session.commit()
    yield
    get_settings.cache_clear()


def _mensagem(texto):
    return NormalizedWhatsAppMessage(telefone=GESTOR, tipo="text", texto=texto, message_id="m")


def _pedido_sem_pendencias(db_session):
    return PedidoService(db_session).criar(
        nome_cliente="Cliente Pedido",
        telefone_cliente="351912345678",
        data_planejada=datetime.now(timezone.utc),
        valor_global="100",
        pago=True,
        forma_pagamento="MBWay",
        pedido_feito_por="gestor",
        endereco_aproximado="Rua",
        ponto_referencia=None,
        residuos=["Entulho Limpo"],
    ).contentores[0]


def _aluguer_legado(db_session, **pendencias):
    SeedService(db_session).seed_contentores_iniciais()
    aluguer = AluguerService(db_session).registrar_novo_aluguer(
        nome_cliente="Cliente Legado",
        telefone_cliente="351922222222",
        valor="180",
        forma_pagamento="MBWay",
        pago=True,
    )
    for campo, valor in pendencias.items():
        setattr(aluguer, campo, valor)
    db_session.commit()
    return aluguer


def test_resolver_carga_nao_altera_registro_legado_sem_pendencia(db_session):
    item = _pedido_sem_pendencias(db_session)
    aluguer = _aluguer_legado(db_session)
    assert item.id == aluguer.id

    resposta = WhatsappRouterAgent(db_session).handle(_mensagem(f"resolver carga {aluguer.id}"))

    db_session.expire_all()
    assert resposta == "⚠️ Esse registro não possui pendência de carga ativa."
    assert db_session.get(AluguerContentor, aluguer.id).status_resolucao_carga == StatusResolucao.NAO_APLICA.value
    assert db_session.query(EventoAluguer).filter_by(tipo="pendencia_carga_resolvida").count() == 0


def test_resolver_carga_legada_pendente_continua_funcionando(db_session):
    aluguer = _aluguer_legado(
        db_session, carga_errada=True, relato_carga="carga misturada", status_resolucao_carga="PENDENTE"
    )

    resposta = WhatsappRouterAgent(db_session).handle(_mensagem(f"resolver carga {aluguer.id}"))

    db_session.expire_all()
    assert "resolvida" in resposta
    assert db_session.get(AluguerContentor, aluguer.id).status_resolucao_carga == StatusResolucao.RESOLVIDO.value


def test_resolver_avaria_encontra_pendencia_legada_com_id_de_item_sem_avaria(db_session):
    item = _pedido_sem_pendencias(db_session)
    aluguer = _aluguer_legado(
        db_session,
        contentor_avariado=True,
        relato_avaria="porta traseira amassada",
        status_resolucao_avaria=StatusResolucao.PENDENTE.value,
    )
    assert item.id == aluguer.id
    router = WhatsappRouterAgent(db_session)

    revisao = router.handle(_mensagem(f"resolver avaria {aluguer.id}"))
    confirmacao = router.handle(_mensagem("1"))

    db_session.expire_all()
    assert "Pedido: registro legado" in revisao
    assert "porta traseira amassada" in revisao
    assert "resolvida" in confirmacao
    assert db_session.get(AluguerContentor, aluguer.id).status_resolucao_avaria == StatusResolucao.RESOLVIDO.value
    assert db_session.get(PedidoContentor, item.id).status_resolucao_avaria == "N/A"


def test_resolver_avaria_sem_pendencia_em_nenhum_modelo_mantem_mensagem(db_session):
    item = _pedido_sem_pendencias(db_session)
    _aluguer_legado(db_session)

    resposta = WhatsappRouterAgent(db_session).handle(_mensagem(f"resolver avaria {item.id}"))

    assert resposta == "Esse equipamento não possui uma pendência de avaria ativa."
