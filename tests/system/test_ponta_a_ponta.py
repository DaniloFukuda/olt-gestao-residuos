"""Operação completa pelo WhatsApp, do pedido ao despejo, via webhook.

Cenário: um gestor cadastra 12 pedidos de contentor (18 contentores) e 10 de
carrinha (12 carrinhas); um motorista faz entrega/chegada, recolha/partida e
despejo de todos. Pelo caminho aparecem pagamentos na criação, na entrega e
pelo gestor depois, dívidas que continuam em aberto, avarias, contentores
trocados dentro do pedido (sem divergência), divergências de carga, número
fora da frota, cancelamento desistido e o painel do gestor.

Tudo passa pelo POST /webhook/whatsapp (parser, deduplicação, fila por
telefone, roteador e agentes). O envio à Meta é substituído pelo
FakeMetaClient, que guarda o texto que seria enviado.
"""

import re
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import func

from app.models.aluguer import ContentorFoto
from app.models.contentor import Contentor, StatusContentor
from app.models.pedido import (
    Pedido,
    PedidoContentor,
    StatusCicloPedido,
    StatusOperacionalCarrinha,
    StatusPagamento,
    StatusResolucaoPedido,
    TipoEquipamentoPedido,
)
from app.services.seed_service import SeedService

from tests.system.helpers.conversation_driver import ConversationDriver
from tests.system.helpers.fake_whatsapp_user import FakeWhatsAppUser

RESIDUO = {"L": "Entulho Limpo", "M": "Entulho Misto"}
OPCAO_RESIDUO = {"L": "1", "M": "2"}
# Listas do WhatsApp: forma no cadastro/entrega e forma no fluxo do gestor.
FORMA_CADASTRO = {"MBWay": "1", "Transferência": "2", "Dinheiro": "3"}
FORMA_GESTOR = {"Dinheiro": "1", "MBWay": "2", "Transferência": "3"}


@dataclass
class PedidoE2E:
    nome: str
    tipo: str  # "contentor" | "carrinha"
    residuos: list[str]  # "L"/"M" por equipamento
    valor: int
    # "pago:<forma>" no cadastro, "entrega:<forma>" pago ao motorista,
    # "gestor:<forma>" registrado depois pelo gestor, "pendente" fica em dívida.
    pagamento: str
    numeros: list[str]  # adesivo do contentor ou frota da carrinha ("0" = sem frota)
    # Despejo, um passo por equipamento: "L"/"M" é o resíduo que caiu (com
    # cota em aberto); "nao:<L|M>:<relato>" o motorista aponta divergência.
    despejo: list[str]
    avaria: str | None = None  # relato na recolha/partida (pedidos de 1 equipamento)
    horario: str = "09:00"
    mao_de_obra: bool = False
    id: int | None = None
    extras: dict = field(default_factory=dict)

    @property
    def forma(self) -> str | None:
        return self.pagamento.split(":", 1)[1] if ":" in self.pagamento else None

    @property
    def fica_pago(self) -> bool:
        return self.pagamento != "pendente"


def _contentores() -> list[PedidoE2E]:
    return [
        PedidoE2E("Obra C01", "contentor", ["L"], 120, "pago:MBWay", ["1"], ["L"]),
        PedidoE2E("Obra C02", "contentor", ["M"], 150, "entrega:Dinheiro", ["2"], ["M"]),
        # Contentores trocados na obra: o "Limpo" veio com Misto e vice-versa.
        PedidoE2E("Obra C03", "contentor", ["L", "M"], 260, "pago:Transferência", ["3", "4"], ["M", "L"]),
        PedidoE2E(
            "Obra C04", "contentor", ["L", "L"], 200, "pendente", ["5", "6"],
            ["L", "nao:M:veio com plastico e madeira"],
        ),
        PedidoE2E(
            "Obra C05", "contentor", ["M"], 90, "gestor:Transferência", ["7"], ["M"],
            avaria="porta traseira empenada",
        ),
        PedidoE2E("Obra C06", "contentor", ["L", "M", "M"], 380, "pago:Dinheiro", ["8", "9", "10"], ["L", "M", "M"]),
        PedidoE2E("Obra C07", "contentor", ["M"], 100, "entrega:MBWay", ["11"], ["M"], mao_de_obra=True),
        PedidoE2E("Obra C08", "contentor", ["L"], 110, "pago:MBWay", ["12"], ["nao:L:limpo mas com terra vegetal"]),
        PedidoE2E("Obra C09", "contentor", ["M", "L"], 240, "pendente", ["13", "14"], ["L", "M"]),
        PedidoE2E("Obra C10", "contentor", ["L"], 95, "pago:Dinheiro", ["15"], ["L"], avaria="roda partida no eixo"),
        PedidoE2E("Obra C11", "contentor", ["M", "M"], 210, "entrega:Transferência", ["16", "17"], ["M", "M"]),
        PedidoE2E("Obra C12", "contentor", ["L"], 130, "pago:Transferência", ["18"], ["L"]),
    ]


def _carrinhas() -> list[PedidoE2E]:
    return [
        PedidoE2E("Obra K01", "carrinha", ["L"], 200, "pago:MBWay", ["3"], ["L"], mao_de_obra=True, horario="08:30"),
        PedidoE2E("Obra K02", "carrinha", ["M"], 180, "gestor:Dinheiro", ["0"], ["M"], horario="09:15"),
        PedidoE2E("Obra K03", "carrinha", ["L", "M"], 320, "pago:MBWay", ["0", "0"], ["M", "L"], horario="10:00"),
        PedidoE2E(
            "Obra K04", "carrinha", ["L"], 250, "pago:Transferência", ["5"], ["L"],
            avaria="lona rasgada na lateral", horario="10:45",
        ),
        PedidoE2E(
            "Obra K05", "carrinha", ["M"], 160, "pendente", ["0"], ["nao:L:era so entulho limpo"],
            horario="11:30",
        ),
        PedidoE2E("Obra K06", "carrinha", ["L"], 140, "pago:Dinheiro", ["7"], ["L"], horario="13:00"),
        PedidoE2E("Obra K07", "carrinha", ["L", "L"], 300, "gestor:MBWay", ["8", "9"], ["L", "L"], horario="14:00"),
        PedidoE2E("Obra K08", "carrinha", ["M"], 170, "pago:MBWay", ["0"], ["M"], horario="15:00"),
        PedidoE2E("Obra K09", "carrinha", ["L"], 150, "pago:Transferência", ["11"], ["L"], horario="16:00"),
        PedidoE2E("Obra K10", "carrinha", ["M"], 190, "pendente", ["12"], ["M"], horario="17:00"),
    ]


def euros(valor) -> str:
    inteiro, centavos = f"{Decimal(valor):.2f}".split(".")
    inteiro = f"{int(inteiro):,}".replace(",", ".")
    return f"{inteiro},{centavos} €"


class Operador:
    """Um telefone no WhatsApp: envia mensagens pelo webhook e lê as respostas."""

    def __init__(self, system_app, fake_meta, telefone, cenario):
        app, SessionLocal, _ids = system_app
        self.driver = ConversationDriver(app, SessionLocal, FakeWhatsAppUser(telefone, cenario), fake_meta)
        self._fotos = 0

    def _checar(self, response) -> str:
        assert response.status_code == 200, response.text
        dados = response.json()
        assert dados.get("failed", 0) == 0, dados
        return "\n".join(self.driver.last_bodies())

    def t(self, texto: str) -> str:
        return self._checar(self.driver.send_text(texto))

    def foto(self) -> str:
        self._fotos += 1
        return self._checar(self.driver.send_image(f"media-{self.driver.user.phone}-{self._fotos:04d}"))

    def local(self) -> str:
        return self._checar(self.driver.send_location(38.7223, -9.1393))

    def escolher(self, resposta: str, nome: str) -> str:
        opcao = re.search(rf"(?m)^\s*(\d+)\.\s+.*?{re.escape(nome)}\b", resposta)
        assert opcao, f"{nome!r} não está na lista:\n{resposta}"
        return self.t(opcao.group(1))


def cadastrar(gestor: Operador, pedido: PedidoE2E) -> None:
    gestor.t("1")
    if pedido.tipo == "contentor":
        gestor.t("1")
        gestor.t(pedido.nome)
        gestor.t("912345678")
        gestor.t(str(len(pedido.residuos)))
        gestor.t("1" if pedido.mao_de_obra else "2")
        for residuo in pedido.residuos:
            gestor.t(OPCAO_RESIDUO[residuo])
        gestor.t("1")  # Hoje
    else:
        gestor.t("2")
        gestor.t(str(len(pedido.residuos)))
        gestor.t(pedido.nome)
        gestor.t("912345679")
        gestor.t("1")  # Hoje
        gestor.t(pedido.horario)
        for residuo in pedido.residuos:
            gestor.t(OPCAO_RESIDUO[residuo])
        gestor.t("1" if pedido.mao_de_obra else "2")
    gestor.t(str(pedido.valor))
    if pedido.pagamento.startswith("pago:"):
        gestor.t("1")
        gestor.t(FORMA_CADASTRO[pedido.forma])
    else:
        gestor.t("2")
    gestor.t(f"Rua da {pedido.nome}, Lisboa")
    confirmacao = gestor.t("2")  # sem ponto de referência
    assert f"Cliente: {pedido.nome}" in confirmacao
    criado = gestor.t("1")
    numero = re.search(r"Pedido #(\d+) criado", criado)
    assert numero, criado
    pedido.id = int(numero.group(1))


def entregar_contentores(motorista: Operador, pedido: PedidoE2E) -> None:
    resposta = motorista.escolher(motorista.t("2"), pedido.nome)
    for indice, numero in enumerate(pedido.numeros):
        if pedido.extras.get("numero_fora_da_frota") and indice == 0:
            recusa = motorista.t(pedido.extras["numero_fora_da_frota"])
            assert "não está cadastrado na frota" in recusa
        assert "Digite o número do contentor" in resposta
        assert "Envie a foto" in motorista.t(numero)
        motorista.foto()
        if pedido.extras.get("foto_extra"):
            motorista.t("1")  # Outra foto
            motorista.foto()
        resposta = motorista.t("2")
    assert "localização GPS" in resposta
    motorista.local()
    confirmacao = motorista.t("2")  # sem ponto de referência
    assert "Confirme a entrega preparada" in confirmacao
    final = motorista.t("1")
    if pedido.pagamento.startswith("pago:"):
        assert "Entrega confirmada com sucesso" in final
        return
    assert "pagamento no local" in final
    if pedido.pagamento.startswith("entrega:"):
        motorista.t("1")
        final = motorista.t(FORMA_CADASTRO[pedido.forma])
        assert "Pagamento registrado" in final
    else:
        final = motorista.t("2")
        assert "Entrega confirmada com sucesso" in final


def chegar_carrinhas(motorista: Operador, pedido: PedidoE2E) -> None:
    resposta = motorista.escolher(motorista.t("2"), pedido.nome)
    for numero in pedido.numeros:
        assert "número da frota" in resposta
        assert "Envie a foto" in motorista.t(numero)
        motorista.foto()
        resposta = motorista.t("2")
    assert "localização GPS" in resposta
    motorista.local()
    motorista.t("2")
    assert "Chegada da carrinha confirmada" in motorista.t("1")


def recolher(motorista: Operador, pedido: PedidoE2E) -> None:
    resposta = motorista.escolher(motorista.t("3"), pedido.nome)
    for _ in pedido.numeros:
        assert "Selecione o ativo para a" in resposta
        assert "Envie a foto" in motorista.t("1")
        motorista.foto()
        if pedido.extras.get("foto_extra"):
            motorista.t("1")  # Outra foto... e desiste: "Próximo passo" direto.
        assert "estrago ou avaria" in motorista.t("2")
        if pedido.avaria:
            motorista.t("2")
            confirmacao = motorista.t(pedido.avaria)
            assert f"Relato: {pedido.avaria}" in confirmacao
        else:
            motorista.t("1")
        resposta = motorista.t("1")
    assert "concluida" in resposta


def despejar(motorista: Operador, pedido: PedidoE2E) -> None:
    resposta = motorista.escolher(motorista.t("4"), pedido.nome)
    for passo in pedido.despejo:
        assert "Selecione o ativo descarregado" in resposta
        pergunta = motorista.t("1")
        if passo.startswith("nao:"):
            _, real, relato = passo.split(":", 2)
            assert "corresponde a" in pergunta
            assert "caiu de fato no chão" in motorista.t("2")
            assert "Descreva a divergência" in motorista.t(OPCAO_RESIDUO[real])
            assert "Envie a foto" in motorista.t(relato)
        elif "Qual resíduo caiu no chão?" in pergunta:
            assert "Envie a foto" in motorista.t(OPCAO_RESIDUO[passo])
        else:
            assert f"corresponde a {RESIDUO[passo]}?" in pergunta
            assert "Envie a foto" in motorista.t("1")
        motorista.foto()
        confirmacao = motorista.t("2")
        esperado = "Sim" if passo.startswith("nao:") else "Nao"
        assert f"Divergencia: {esperado}" in confirmacao
        resposta = motorista.t("1")
    assert "concluído" in resposta or "Nenhum" in resposta


def registrar_pagamento(gestor: Operador, pedido: PedidoE2E) -> None:
    lista = gestor.t("registrar pagamento")
    revisao = gestor.escolher(lista, f"Pedido #{pedido.id} • {pedido.nome}")
    assert "Escolha a forma" in revisao
    gestor.t(FORMA_GESTOR[pedido.forma])
    assert "Pagamento registrado" in gestor.t("1")


def test_operacao_completa_de_22_pedidos_pelo_whatsapp(
    system_app, gestor, funcionario, fake_meta, db_assertions, system_db
):
    with system_db() as session:
        SeedService(session).seed_contentores_iniciais()
    g = Operador(system_app, fake_meta, gestor, "E2E-GESTOR")
    m = Operador(system_app, fake_meta, funcionario, "E2E-MOTORISTA")
    CONTENTORES, CARRINHAS = _contentores(), _carrinhas()
    CONTENTORES[11].extras["numero_fora_da_frota"] = "25"
    CONTENTORES[5].extras["foto_extra"] = True
    CARRINHAS[2].extras["foto_extra"] = True
    pedidos = CONTENTORES + CARRINHAS

    # 1. Cadastro pelo gestor; motorista não cadastra.
    assert "não possui permissão" in m.t("novo")
    for indice, pedido in enumerate(pedidos):
        if indice == 8:
            # Cancelamento pedido por engano e desistido no meio do cadastro.
            g.t("1")
            g.t("1")
            assert "Deseja cancelar" in g.t("voltar")
            assert "Operação retomada" in g.t("2")
            g.t("cancelar")
            assert "Operação cancelada" in g.t("1")
        cadastrar(g, pedido)
    db_assertions.assert_pedido_count(22)
    db_assertions.assert_contentor_count(30)
    painel = g.t("5")
    assert all(p.nome in painel for p in pedidos)

    # 2. Entrega dos contentores e chegada das carrinhas.
    for pedido in CONTENTORES:
        entregar_contentores(m, pedido)
    for pedido in CARRINHAS:
        chegar_carrinhas(m, pedido)
    with system_db() as session:
        alugados = {
            c.codigo for c in session.query(Contentor).filter_by(status=StatusContentor.ALUGADO)
        }
    assert alugados == {str(n) for n in range(1, 19)}
    lista_alugados = g.t("alugados")
    assert all(f"{p.nome} - vencimento" in lista_alugados for p in CONTENTORES)

    # 3. Recolha e partida.
    for pedido in pedidos:
        recolher(m, pedido)

    # 4. Despejo no vazadouro.
    for pedido in pedidos:
        despejar(m, pedido)

    # 5. Pagamentos registrados depois pelo gestor.
    for pedido in pedidos:
        if pedido.pagamento.startswith("gestor:"):
            registrar_pagamento(g, pedido)

    # 6. Estado final no banco.
    with system_db() as session:
        itens = session.query(PedidoContentor).all()
        assert all(item.status_ciclo == StatusCicloPedido.CONCLUIDO.value for item in itens)
        assert all(
            item.status_operacional_carrinha == StatusOperacionalCarrinha.CONCLUIDA.value
            for item in itens
            if item.tipo_equipamento == TipoEquipamentoPedido.CARRINHA.value
        )
        por_id = {p.id: p for p in pedidos}
        for registro in session.query(Pedido).all():
            esperado = por_id[registro.id]
            assert registro.status_pagamento == (
                StatusPagamento.PAGO.value if esperado.fica_pago else StatusPagamento.PENDENTE.value
            ), esperado.nome
            if esperado.fica_pago:
                assert registro.pagamento_recebido_em is not None, esperado.nome
                assert registro.forma_pagamento == esperado.forma, esperado.nome
        cargas = {
            (item.pedido.nome_cliente, item.residuo_efetivo_vazadouro)
            for item in itens
            if item.status_resolucao_carga == StatusResolucaoPedido.PENDENTE.value
        }
        assert cargas == {
            ("Obra C04", "Entulho Misto"),
            ("Obra C08", "Entulho Limpo"),
            ("Obra K05", "Entulho Limpo"),
        }
        trocados = [item for item in itens if item.pedido.nome_cliente in {"Obra C03", "Obra K03"}]
        assert all(item.carga_errada is False for item in trocados)
        assert any(item.residuo_efetivo_vazadouro != item.residuo_contratado for item in trocados)
        avarias = {
            item.pedido.nome_cliente: item.id
            for item in itens
            if item.status_resolucao_avaria == StatusResolucaoPedido.PENDENTE.value
        }
        assert set(avarias) == {"Obra C05", "Obra C10", "Obra K04"}
        manutencao = {
            c.codigo for c in session.query(Contentor).filter_by(status=StatusContentor.MANUTENCAO)
        }
        assert manutencao == {"7", "15"}
        carga_c08 = next(item.id for item in itens if item.pedido.nome_cliente == "Obra C08")

    # 7. Painel do gestor: financeiro e pendências.
    painel = g.t("5")
    caixa = sum(p.valor for p in pedidos if p.fica_pago)
    receber = sum(p.valor for p in pedidos if not p.fica_pago)
    assert f"Total faturado — caixa: {euros(caixa)}" in painel
    assert f"Total a receber: {euros(receber)}" in painel
    assert f"Total projetado: {euros(caixa + receber)}" in painel
    for pedido in pedidos:
        if not pedido.fica_pago:
            assert f"{pedido.nome} • Em dívida: {euros(pedido.valor)}" in painel
    avarias_painel = painel.split("Avarias em Equipamentos")[1]
    for nome in ("Obra C05", "Obra C10", "Obra K04"):
        assert nome in avarias_painel
    cargas_painel = painel.split("Cargas com Divergência no Despejo")[1]
    for nome in ("Obra C04", "Obra C08", "Obra K05"):
        assert nome in cargas_painel
    painel_motorista = m.t("5")
    assert "Cargas com Divergência" not in painel_motorista
    assert "RESUMO FINANCEIRO" not in painel_motorista

    # 8. Gestor resolve avarias (frota volta a disponível) e uma carga.
    for nome, item_id in avarias.items():
        revisao = g.t(f"resolver avaria {item_id}")
        assert "Revisão de resolução de avaria" in revisao and nome in revisao
        if nome == "Obra K04":
            assert "Equipamento Nº 5 (carrinha)" in revisao
        assert "resolvida" in g.t("1"), nome
    assert "resolvida" in g.t(f"resolver carga {carga_c08}")
    assert "cadastrado na frota" in g.t("cadastrar contentor 25")
    with system_db() as session:
        assert {c.status for c in session.query(Contentor).all()} == {StatusContentor.DISPONIVEL}
        pendentes_carga = session.query(PedidoContentor).filter_by(
            status_resolucao_carga=StatusResolucaoPedido.PENDENTE.value
        ).count()
        assert pendentes_carga == 2
        fotos = dict(
            session.query(ContentorFoto.tipo_foto, func.count()).group_by(ContentorFoto.tipo_foto).all()
        )
    # 18 contentores + 3 fotos extra (Obra C06) + 12 carrinhas; 1 foto por
    # equipamento na recolha/partida e no despejo.
    assert fotos == {"ENTREGA": 33, "RECOLHA": 30, "DESPEJO": 30}
    assert "Cargas com Divergência" in g.t("5")

    # 9. Infraestrutura do webhook: tudo processado, fila vazia, nada saiu para a Meta.
    db_assertions.assert_all_dedup_completed()
    db_assertions.assert_no_active_queue()
    db_assertions.assert_quick_check_ok()
    assert fake_meta.external_attempts == []
    assert len(fake_meta.sent) > 900
