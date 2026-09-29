"""Regras de despejo compartilhadas por contentor, carrinha e backend legado.

A mesma etapa do despejo é decidida em três lugares (``contentor.py``,
``carrinha.py`` e ``PedidoV24Agent``). As regras ficam aqui para que os três
não voltem a divergir.

Regra de negócio: a divergência vale pelo total do pedido. Um pedido com
um contentor de Entulho Limpo e outro de Entulho Misto pode ter os dois
trocados na obra; enquanto o resíduo despejado tiver cota em aberto no
pedido, não há divergência. Há divergência só quando o motorista responde
que a carga não corresponde à cota que resta ("Não" na conformidade). Nesse
caso ele informa o resíduo que caiu de fato, que é gravado como resíduo
efetivo, e o despejo abre pendência de carga com relato.
"""

RESIDUOS_DESPEJO = ("Entulho Limpo", "Entulho Misto")

RESIDUO_REAL_PROMPT = (
    "Qual resíduo caiu de fato no chão?\n\n"
    "1. 🟢 Entulho Limpo\n"
    "2. 🟠 Entulho Misto"
)
RELATO_PROMPT = "Descreva a divergência com pelo menos 10 caracteres."

# Escolhas já normalizadas (minúsculas, sem acentos; emojis preservados).
CONFORMIDADE_SIM = {
    "1", "sim", "sim, corresponde", "✅ sim, corresponde",
    "sim, tudo certo", "✅ sim, tudo certo",
}
CONFORMIDADE_NAO = {
    "2", "nao", "nao, existe divergencia", "❌ nao, existe divergencia",
    "nao, esta misturado/errado", "🚨 nao, esta misturado/errado",
}


def normalizar_conformidade(choice: str) -> str:
    if choice == "despejo_conformidade:sim":
        return "1"
    if choice == "despejo_conformidade:nao":
        return "2"
    return choice


def residuo_escolhido(choice: str, disponiveis, normalize) -> str | None:
    """Traduz a resposta (botão, número ou nome) para um resíduo da lista."""
    disponiveis = list(disponiveis or [])
    if choice == "despejo_residuo:limpo":
        return "Entulho Limpo"
    if choice == "despejo_residuo:misto":
        return "Entulho Misto"
    if choice.isdigit() and 1 <= int(choice) <= len(disponiveis):
        return disponiveis[int(choice) - 1]
    return next((item for item in disponiveis if normalize(item) == choice), None)


def aplicar_residuo(ctx: dict, residuo: str) -> bool:
    """Grava o resíduo informado; devolve True quando o fluxo precisa de relato."""
    ctx["residuo_efetivo"] = residuo
    ctx["relato_carga"] = None
    divergente = bool(ctx.get("divergencia_reportada"))
    ctx["carga_errada"] = divergente
    return divergente


def aplicar_conformidade_sim(ctx: dict) -> None:
    ctx["residuo_efetivo"] = ctx.get("residuo_assumido") or ctx["residuo_contratado"]
    ctx["carga_errada"] = False
    ctx["relato_carga"] = None
    ctx.pop("divergencia_reportada", None)


def aplicar_conformidade_nao(ctx: dict) -> None:
    """Prepara a pergunta do resíduo real depois de o motorista apontar divergência."""
    ctx["divergencia_reportada"] = True
    ctx["carga_errada"] = True
    ctx["residuo_efetivo"] = None
    ctx["relato_carga"] = None
    ctx["residuos_disponiveis"] = list(RESIDUOS_DESPEJO)


def aplicar_relato(ctx: dict, relato: str) -> None:
    ctx["relato_carga"] = relato
    ctx["carga_errada"] = True
    ctx["residuo_efetivo"] = (
        ctx.get("residuo_efetivo")
        or ctx.get("residuo_assumido")
        or ctx.get("residuo_contratado")
    )
