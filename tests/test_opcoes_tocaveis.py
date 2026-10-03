"""Perguntas com respostas padronizadas viram botões ou listas (regra de UX de 03/10/2026).

O utilizador digita só dados livres. Ver app/agents/pedido_v24/opcoes.py.
"""

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.agents.pedido_v24 import opcoes
from app.agents.whatsapp_router_agent import WhatsappRouterAgent
from app.integrations.whatsapp.client import send_whatsapp_message
from app.models.contentor import Contentor, StatusContentor
from app.models.conversa import ConversaWhatsApp
from app.services.pedido_service import PedidoService
from app.services.seed_service import SeedService

from tests.test_pedido_v24 import liberar_operadores, msg


def toque(reply_id):
    """Resposta de botão/lista: o parser entrega o id (option_N vira N)."""
    texto = reply_id.removeprefix("option_") if reply_id.startswith("option_") else reply_id
    return msg(texto, kind="interactive")


def render(body):
    return send_whatsapp_message("351900000000", body, force_mock=True)


def ids(resultado):
    linhas = []
    for parte in [resultado, *(resultado.get("additional_messages") or [])]:
        linhas.extend(parte.get("buttons") or parte.get("list_rows") or [])
    return [linha["id"] for linha in linhas]


def estado(db_session):
    db_session.expire_all()
    return db_session.query(ConversaWhatsApp).one()


def hoje_lisboa():
    return datetime.now(ZoneInfo("Europe/Lisbon")).date()


# --- Como as perguntas chegam ao WhatsApp ---------------------------------


def test_tipo_de_solicitacao_vira_dois_botoes(db_session, monkeypatch):
    liberar_operadores(monkeypatch)
    resultado = render(WhatsappRouterAgent(db_session).handle(msg("1")))

    assert resultado["interactive_type"] == "button"
    assert [b["title"] for b in resultado["buttons"]] == ["📦 Contentor", "🚛 Carrinha"]


def test_quantidade_oferece_1_2_3_e_4_ou_mais():
    resultado = render(opcoes.quantidade_prompt(carrinha=True))

    assert resultado["interactive_type"] == "list"
    assert [r["title"] for r in resultado["list_rows"]] == ["1 carrinha", "2 carrinhas", "3 carrinhas", "✏️ 4 ou mais"]
    assert ids(resultado) == ["option_1", "option_2", "option_3", "digitar"]


def test_datas_e_horarios_levam_o_proprio_valor_como_id():
    datas = render(opcoes.data_lista_prompt(date(2026, 10, 3)))
    horarios = render(opcoes.horario_prompt())

    assert ids(datas)[0] == "05/10/2026"
    assert datas["list_rows"][0]["title"] == "Seg 05/10/2026"
    assert ids(datas)[-1] == "digitar" and len(ids(datas)) == 9
    assert ids(horarios) == [*opcoes.HORARIOS, "digitar"]


def test_frota_da_carrinha_tem_botao_sem_frota():
    resultado = render("Digite o número da frota da carrinha alocada ou toque em Sem frota:")

    assert resultado["interactive_type"] == "button"
    assert resultado["buttons"] == [{"id": "option_0", "title": "🚫 Sem frota"}]


def test_avaria_e_pagamento_no_local_cabem_em_botoes():
    avaria = render("O equipamento sofreu algum estrago ou avaria na obra?\n\n1. ✅ Sem avaria\n2. 💥 Com avaria")
    pagamento = render("O cliente realizou o pagamento no local?\n\n1. ✅ Sim, foi pago\n2. 🕒 Não, pendente")

    assert avaria["interactive_type"] == "button"
    assert pagamento["interactive_type"] == "button"


# --- Respostas tocadas chegam aos tratadores ------------------------------


def _ate_quantidade(router):
    for texto in ["1", "1", "Cliente Toque", "912345678"]:
        router.handle(msg(texto))


def test_quantidade_4_ou_mais_pede_digitacao_sem_mudar_de_etapa(db_session, monkeypatch):
    liberar_operadores(monkeypatch)
    router = WhatsappRouterAgent(db_session)
    _ate_quantidade(router)

    pergunta = router.handle(toque("digitar"))
    assert pergunta == opcoes.QUANTIDADE_DIGITAR
    assert estado(db_session).estado_atual == "v24_cadastro_quantidade"
    router.handle(msg("6"))

    assert estado(db_session).contexto_json["quantidade"] == 6


def test_quantidade_tocada_avanca(db_session, monkeypatch):
    liberar_operadores(monkeypatch)
    router = WhatsappRouterAgent(db_session)
    _ate_quantidade(router)

    router.handle(toque("option_2"))

    assert estado(db_session).contexto_json["quantidade"] == 2


def _ate_outra_data(router):
    _ate_quantidade(router)
    for texto in ["1", "2", "1"]:  # 1 contentor, sem pessoal, Entulho Limpo
        router.handle(msg(texto))
    return router.handle(toque("option_3"))  # Outra data


def test_outra_data_mostra_proximos_dias_e_aceita_toque(db_session, monkeypatch):
    liberar_operadores(monkeypatch)
    router = WhatsappRouterAgent(db_session)
    lista = _ate_outra_data(router)
    dia = hoje_lisboa() + timedelta(days=3)

    assert "Qual o dia da entrega?" in lista
    assert router.handle(toque("digitar")) == opcoes.DATA_DIGITAR
    resposta = router.handle(toque(f"{dia:%d/%m/%Y}"))

    conversa = estado(db_session)
    assert "valor" in resposta.lower()
    assert conversa.estado_atual == "v24_cadastro_valor"
    assert conversa.contexto_json["data"].startswith(dia.isoformat())


def test_outra_data_aceita_o_numero_da_opcao_digitado(db_session, monkeypatch):
    liberar_operadores(monkeypatch)
    router = WhatsappRouterAgent(db_session)
    _ate_outra_data(router)

    router.handle(msg("1"))

    dia = hoje_lisboa() + timedelta(days=2)
    assert estado(db_session).contexto_json["data"].startswith(dia.isoformat())


def _ate_horario(router):
    for texto in ["1", "2", "1", "Cliente Hora", "912345678"]:
        router.handle(msg(texto))
    return router.handle(toque("option_1"))  # Hoje


def test_horario_tocado_digitado_ou_por_numero(db_session, monkeypatch):
    liberar_operadores(monkeypatch)
    router = WhatsappRouterAgent(db_session)
    lista = _ate_horario(router)

    assert "10. ✏️ Outro horário" in lista
    assert router.handle(toque("digitar")) == opcoes.HORARIO_DIGITAR
    assert "Resíduo da carrinha" in router.handle(toque("09:00"))
    assert estado(db_session).contexto_json["horario_agendado"] == "09:00"


def test_horario_pelo_numero_da_opcao(db_session, monkeypatch):
    liberar_operadores(monkeypatch)
    router = WhatsappRouterAgent(db_session)
    _ate_horario(router)

    router.handle(msg("3"))

    assert estado(db_session).contexto_json["horario_agendado"] == "10:00"


def test_corrigir_dia_da_carrinha_pergunta_a_hora_em_seguida(db_session, monkeypatch):
    liberar_operadores(monkeypatch)
    router = WhatsappRouterAgent(db_session)
    _ate_horario(router)
    for texto in ["09:00", "1", "2", "200", "2", "Rua", "2"]:
        router.handle(msg(texto))
    router.handle(toque("option_2"))  # Corrigir
    lista = router.handle(toque("corrigir_pedido:data_entrega"))
    dia = hoje_lisboa() + timedelta(days=2)

    assert "Qual o dia da chegada?" in lista and "1. Hoje" in lista
    hora = router.handle(toque(f"{dia:%d/%m/%Y}"))
    assert "horário agendado" in hora
    confirmacao = router.handle(toque("15:00"))

    conversa = estado(db_session)
    assert conversa.estado_atual == "v24_cadastro_confirmacao"
    assert conversa.contexto_json["horario_agendado"] == "15:00"
    assert conversa.contexto_json["data"].startswith(dia.isoformat())
    assert "Hora da chegada: 15:00" in confirmacao


# --- Entrega: número do contentor e frota da carrinha ---------------------


def _pedido(service, residuos=("Entulho Limpo",), itens=None):
    kwargs = {"itens": itens} if itens else {"residuos": list(residuos)}
    return service.criar(
        nome_cliente="Cliente Frota Toque",
        telefone_cliente="351912345678",
        data_planejada=datetime.now(timezone.utc),
        valor_global="100",
        pago=True,
        forma_pagamento="MBWay",
        pedido_feito_por="gestor",
        endereco_aproximado="Rua",
        ponto_referencia=None,
        **kwargs,
    )


def test_entrega_lista_contentores_disponiveis_e_aceita_toque(db_session, monkeypatch):
    liberar_operadores(monkeypatch)
    SeedService(db_session).seed_contentores_iniciais()
    for codigo in ("1", "2"):
        db_session.query(Contentor).filter_by(codigo=codigo).one().status = StatusContentor.ALUGADO
    db_session.commit()
    _pedido(PedidoService(db_session), residuos=("Entulho Limpo", "Entulho Misto"))
    router = WhatsappRouterAgent(db_session)
    router.handle(msg("2"))

    pergunta = router.handle(toque("entrega_pedido:1"))
    linhas = ids(render(pergunta))

    assert "Contentores disponíveis: 3, 4, 5" in pergunta
    assert "adesivo:1" not in linhas and "adesivo:2" not in linhas
    assert linhas[0] == "adesivo:3" and linhas[-1] == "digitar"
    assert "Envie a foto do Contentor 7" in router.handle(toque("adesivo:7"))
    router.handle(msg(kind="image", media="foto-7"))
    segunda = router.handle(toque("option_2"))
    assert "adesivo:7" not in ids(render(segunda))
    assert router.handle(toque("digitar")) == opcoes.ADESIVO_DIGITAR
    assert "Envie a foto do Contentor 9" in router.handle(msg("9"))


def test_chegada_da_carrinha_aceita_botao_sem_frota(db_session, monkeypatch):
    liberar_operadores(monkeypatch)
    _pedido(
        PedidoService(db_session),
        itens=[{"tipo_equipamento": "CARRINHA", "residuo_contratado": "Entulho Limpo", "horario_agendado": "09:00"}],
    )
    router = WhatsappRouterAgent(db_session)
    router.handle(msg("2"))
    pergunta = router.handle(toque("entrega_pedido:1"))

    assert render(pergunta)["buttons"] == [{"id": "option_0", "title": "🚫 Sem frota"}]
    assert "Contentores disponíveis" not in pergunta
    assert "Envie a foto" in router.handle(toque("option_0"))


def test_listagens_informativas_nao_viram_opcoes(db_session, monkeypatch):
    # "1 - disponível", "2 - alugado"... seriam lidos como opções; tocar
    # mandaria "1" ao menu. As listagens começam com "•" e saem em texto.
    liberar_operadores(monkeypatch)
    SeedService(db_session).seed_contentores_iniciais()
    service = PedidoService(db_session)
    pedido = _pedido(service, residuos=("Entulho Limpo", "Entulho Misto"))
    service.confirmar_entrega_lote(
        pedido.id, "motorista", 38.7, -9.1, None,
        [
            {"contentor_id": pedido.contentores[0].id, "numero_adesivo": "1", "fotos": ["f1"]},
            {"contentor_id": pedido.contentores[1].id, "numero_adesivo": "2", "fotos": ["f2"]},
        ],
    )
    router = WhatsappRouterAgent(db_session)

    for comando in ("lista", "disponiveis", "alugados"):
        resposta = router.handle(msg(comando))
        resultado = render(resposta)
        assert "interactive_type" not in resultado, (comando, resposta)
    assert "• 1 - alugado" in router.handle(msg("lista"))
