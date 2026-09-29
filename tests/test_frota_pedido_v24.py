"""Frota de contentores nos pedidos V24.

Regra de negócio: a entrega só aceita contentor cadastrado e disponível; a
entrega marca-o como alugado e o despejo devolve-o a disponível (ou a
manutenção quando a recolha registou avaria pendente). O gestor cadastra
números novos com "cadastrar contentor N".
"""

from datetime import datetime, timezone

from app.agents.whatsapp_router_agent import WhatsappRouterAgent
from app.models.contentor import Contentor, StatusContentor
from app.models.conversa import ConversaWhatsApp
from app.models.operador import Operador, PerfilOperador
from app.models.pedido import StatusEntregaPedido
from app.services.pedido_service import PedidoService
from app.services.seed_service import SeedService

from tests.test_pedido_v24 import liberar_operadores, msg


def _pedido(service, nome="Cliente Frota", residuos=("Entulho Limpo",)):
    return service.criar(
        nome_cliente=nome,
        telefone_cliente="351912345678",
        data_planejada=datetime.now(timezone.utc),
        valor_global="100",
        pago=True,
        forma_pagamento="MBWay",
        pedido_feito_por="gestor",
        endereco_aproximado="Rua",
        ponto_referencia=None,
        residuos=list(residuos),
    )


def _status(db_session, codigo):
    db_session.expire_all()
    return db_session.query(Contentor).filter_by(codigo=codigo).one().status


def _entregar_pelo_whatsapp(router, numero):
    router.handle(msg("2"))
    router.handle(msg("1"))
    resposta = router.handle(msg(numero))
    if "Envie a foto" not in resposta:
        return resposta
    router.handle(msg(kind="image", media=f"foto-{numero}"))
    router.handle(msg("2"))
    router.handle(msg(kind="location", lat=38.7, lon=-9.1))
    router.handle(msg("Não"))
    return router.handle(msg("1"))


def test_entrega_recusa_numero_fora_da_frota_e_mantem_etapa(db_session, monkeypatch):
    liberar_operadores(monkeypatch)
    SeedService(db_session).seed_contentores_iniciais()
    _pedido(PedidoService(db_session))
    router = WhatsappRouterAgent(db_session)

    resposta = _entregar_pelo_whatsapp(router, "25")

    assert "O contentor 25 não está cadastrado na frota" in resposta
    assert "cadastrar contentor 25" in resposta
    assert db_session.query(ConversaWhatsApp).one().estado_atual == "v24_entrega_adesivo"


def test_ciclo_completo_atualiza_status_da_frota(db_session, monkeypatch):
    liberar_operadores(monkeypatch)
    SeedService(db_session).seed_contentores_iniciais()
    service = PedidoService(db_session)
    pedido = _pedido(service)
    router = WhatsappRouterAgent(db_session)

    final = _entregar_pelo_whatsapp(router, "3")

    assert "Entrega confirmada com sucesso" in final
    assert _status(db_session, "3") == StatusContentor.ALUGADO

    _pedido(service, nome="Outro Cliente")
    outra = _entregar_pelo_whatsapp(router, "3")
    assert "O contentor 3 já está alugado" in outra or "ciclo ativo" in outra
    router.handle(msg("menu"))

    item = pedido.contentores[0]
    service.confirmar_recolha(item.id, "motorista", False, None)
    assert _status(db_session, "3") == StatusContentor.ALUGADO
    service.confirmar_despejo(item.id, "Entulho Limpo", operador="motorista", fotos=["d3"])
    assert _status(db_session, "3") == StatusContentor.DISPONIVEL


def test_avaria_pendente_deixa_contentor_em_manutencao_ate_resolver(db_session, monkeypatch):
    liberar_operadores(monkeypatch)
    SeedService(db_session).seed_contentores_iniciais()
    service = PedidoService(db_session)
    pedido = _pedido(service)
    item = pedido.contentores[0]
    service.confirmar_entrega_lote(
        pedido.id, "motorista", 38.7, -9.1, None,
        [{"contentor_id": item.id, "numero_adesivo": "4", "fotos": ["f4"]}],
    )
    service.confirmar_recolha(item.id, "motorista", True, "porta traseira empenada")
    service.confirmar_despejo(item.id, "Entulho Limpo", operador="motorista", fotos=["d4"])
    assert _status(db_session, "4") == StatusContentor.MANUTENCAO

    _pedido(service, nome="Cliente Seguinte")
    router = WhatsappRouterAgent(db_session)
    recusa = _entregar_pelo_whatsapp(router, "4")
    assert "O contentor 4 está em manutenção" in recusa
    router.handle(msg("menu"))

    revisao = router.handle(msg(f"resolver avaria {item.id}"))
    assert "porta traseira empenada" in revisao
    resolvida = router.handle(msg("1"))
    assert "resolvida" in resolvida
    assert _status(db_session, "4") == StatusContentor.DISPONIVEL


def test_numero_com_zero_a_esquerda_usa_o_mesmo_contentor_da_frota(db_session, monkeypatch):
    liberar_operadores(monkeypatch)
    SeedService(db_session).seed_contentores_iniciais()
    service = PedidoService(db_session)
    pedido = _pedido(service)
    item = pedido.contentores[0]

    service.confirmar_entrega_lote(
        pedido.id, "motorista", 38.7, -9.1, None,
        [{"contentor_id": item.id, "numero_adesivo": "07", "fotos": ["f7"]}],
    )

    assert item.status_entrega == StatusEntregaPedido.ENTREGUE.value
    assert _status(db_session, "7") == StatusContentor.ALUGADO
    assert "já está alugado" in service.erro_frota_entrega("7")


def test_frota_vazia_nao_bloqueia_entrega(db_session, monkeypatch):
    liberar_operadores(monkeypatch)
    _pedido(PedidoService(db_session))
    router = WhatsappRouterAgent(db_session)

    assert "Entrega confirmada com sucesso" in _entregar_pelo_whatsapp(router, "501")


def test_gestor_cadastra_contentor_novo_e_motorista_nao_pode(db_session, monkeypatch):
    liberar_operadores(monkeypatch)
    SeedService(db_session).seed_contentores_iniciais()
    db_session.add_all([
        Operador(
            telefone_whatsapp="351900009900",
            nome_operador="Gestor",
            perfil=PerfilOperador.GESTOR,
            ativo=True,
        ),
        Operador(
            telefone_whatsapp="351900000777",
            nome_operador="Motorista",
            perfil=PerfilOperador.FUNCIONARIO,
            ativo=True,
        ),
    ])
    db_session.commit()
    router = WhatsappRouterAgent(db_session)

    assert router.handle(msg("cadastrar contentor 25", phone="351900000777")) == "Operação não permitida."
    criado = router.handle(msg("Cadastrar contentor 25"))
    repetido = router.handle(msg("cadastrar contentor 25"))
    invalido = router.handle(msg("cadastrar contentor C7"))
    grande = router.handle(msg("cadastrar contentor 101"))

    assert criado == "✅ Contentor 25 cadastrado na frota como disponível."
    assert repetido == "O contentor 25 já está na frota (disponivel)."
    assert "Número de contentor inválido" in invalido
    assert grande == "✅ Contentor 101 cadastrado na frota como disponível."
    assert _status(db_session, "25") == StatusContentor.DISPONIVEL

    _pedido(PedidoService(db_session))
    assert "Entrega confirmada com sucesso" in _entregar_pelo_whatsapp(router, "25")
    assert _status(db_session, "25") == StatusContentor.ALUGADO


def test_cadastrar_reativa_contentor_excluido(db_session):
    SeedService(db_session).seed_contentores_iniciais()
    contentor = db_session.query(Contentor).filter_by(codigo="9").one()
    contentor.is_deleted = True
    contentor.status = StatusContentor.MANUTENCAO
    db_session.commit()

    reativado, criado = PedidoService(db_session).cadastrar_contentor_frota("9", "gestor")

    assert criado is True
    assert reativado.is_deleted is False
    assert reativado.status == StatusContentor.DISPONIVEL
