"""Opções tocáveis das perguntas do Pedido V24 (botões e listas do WhatsApp).

Regra de UX (Paulo, 03/10/2026): o utilizador digita o mínimo. Perguntas
com respostas padronizadas oferecem opções; digitar fica para valor, nomes,
telefone, endereço, relatos e para a opção "✏️ ..." de cada lista.

Como a mesma etapa é tratada em até três lugares (agente de contentor, de
carrinha e backend), as respostas tocadas chegam já no formato que esses
tratadores aceitam digitado:

- o cliente WhatsApp dá às linhas de data e horário o próprio valor como id
  ("05/10/2026", "09:00") e às linhas "✏️ ..." o id ``digitar``;
- ``traduzir_resposta`` (chamado pelo roteador V24) troca "digitar" pela
  pergunta de digitação e um número da lista pelo valor correspondente,
  para quem responde digitando o número da opção.
"""

from datetime import date, timedelta

DIGITAR = "digitar"
HORARIOS = ("08:00", "09:00", "10:00", "11:00", "12:00", "13:00", "14:00", "15:00", "16:00")
DIAS_SEMANA = ("Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom")
DIAS_LISTA = 8  # depois de amanhã + 7 dias

QUANTIDADE_DIGITAR = "🔢 Digite a quantidade (4 ou mais):"
DATA_DIGITAR = "📅 Digite a data no formato DD/MM/AAAA:"
HORARIO_DIGITAR = "⏰ Digite o horário no formato HH:MM (ex.: 14:30):"
ADESIVO_DIGITAR = "Digite o número do contentor que está a descarregar:"


def quantidade_prompt(carrinha: bool) -> str:
    if carrinha:
        pergunta = "🔢 Quantas carrinhas são necessárias para este pedido?"
        singular, plural = "carrinha", "carrinhas"
    else:
        pergunta = "🔢 Quantos contentores são necessários para este pedido?"
        singular, plural = "contentor", "contentores"
    return (
        f"{pergunta}\n\n"
        f"1. 1 {singular}\n2. 2 {plural}\n3. 3 {plural}\n4. ✏️ 4 ou mais"
    )


def _rotulo_data(dia: date) -> str:
    return f"{DIAS_SEMANA[dia.weekday()]} {dia:%d/%m/%Y}"


def datas_proximas(hoje: date) -> list[date]:
    return [hoje + timedelta(days=offset) for offset in range(2, 2 + DIAS_LISTA)]


def data_lista_prompt(hoje: date, evento: str = "entrega") -> str:
    linhas = [f"📅 Qual o dia da {evento}?", ""]
    linhas.extend(f"{indice}. {_rotulo_data(dia)}" for indice, dia in enumerate(datas_proximas(hoje), 1))
    linhas.append(f"{DIAS_LISTA + 1}. ✏️ Outra data")
    return "\n".join(linhas)


def data_edicao_prompt(hoje: date, evento: str = "entrega") -> str:
    """Correção da data: Hoje, Amanhã, os próximos dias e Outra data (10 linhas)."""
    linhas = [f"📅 Qual o dia da {evento}?", "", "1. Hoje", "2. Amanhã"]
    linhas.extend(
        f"{indice}. {_rotulo_data(dia)}"
        for indice, dia in enumerate(datas_proximas(hoje)[:DIAS_LISTA - 1], 3)
    )
    linhas.append(f"{DIAS_LISTA + 2}. ✏️ Outra data")
    return "\n".join(linhas)


def horario_prompt() -> str:
    linhas = ["⏰ Qual o horário agendado da carrinha?", ""]
    linhas.extend(f"{indice}. {hora}" for indice, hora in enumerate(HORARIOS, 1))
    linhas.append(f"{len(HORARIOS) + 1}. ✏️ Outro horário")
    return "\n".join(linhas)


def _numero(texto: str) -> int | None:
    texto = (texto or "").strip()
    return int(texto) if texto.isdigit() else None


def traduzir_resposta(estado: str, contexto: dict, texto: str, hoje: date) -> tuple[str | None, str | None]:
    """Devolve (pergunta, texto_traduzido).

    ``pergunta`` preenchida: responder com ela sem mudar o estado (o
    utilizador escolheu "✏️ ..."). ``texto_traduzido`` preenchido: tratar a
    mensagem como se tivesse esse texto. Ambos None: seguir como veio.
    """
    campo = (contexto or {}).get("editing_field")
    texto = (texto or "").strip()
    if texto == DIGITAR:
        if estado == "v24_cadastro_quantidade" or (estado.startswith("v24_cadastro_edicao") and campo == "quantidade"):
            return QUANTIDADE_DIGITAR, None
        if estado in {"v24_cadastro_data_manual", "v24_cadastro_edicao_data"}:
            return DATA_DIGITAR, None
        if estado == "v24_cadastro_horario_carrinha":
            return HORARIO_DIGITAR, None
        if estado == "v24_entrega_adesivo":
            return ADESIVO_DIGITAR, None
        return None, None
    numero = _numero(texto)
    if numero is None:
        return None, None
    if estado == "v24_cadastro_data_manual":
        dias = datas_proximas(hoje)
        if 1 <= numero <= len(dias):
            return None, f"{dias[numero - 1]:%d/%m/%Y}"
        if numero == len(dias) + 1:
            return DATA_DIGITAR, None
    if estado == "v24_cadastro_edicao_data":
        dias = datas_proximas(hoje)[:DIAS_LISTA - 1]
        if 3 <= numero < 3 + len(dias):
            return None, f"{dias[numero - 3]:%d/%m/%Y}"
        if numero == DIAS_LISTA + 2:
            return DATA_DIGITAR, None
    if estado == "v24_cadastro_horario_carrinha":
        if 1 <= numero <= len(HORARIOS):
            return None, HORARIOS[numero - 1]
        if numero == len(HORARIOS) + 1:
            return HORARIO_DIGITAR, None
    return None, None
