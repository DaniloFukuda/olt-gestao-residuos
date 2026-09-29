import re
from decimal import Decimal, InvalidOperation


VALOR_MAXIMO = Decimal("99999999.99")
VALOR_INVALIDO_MESSAGE = "Valor inválido."

_SUFIXOS_MOEDA = ("euros", "euro", "eur", "€")
_NUMERO = re.compile(r"\d+(?:[.,]\d+)*")


def parse_valor_monetario(raw: str | None) -> Decimal | None:
    """Converte texto livre do WhatsApp em euros; devolve None quando inválido.

    Aceita "150", "150,50", "150.50", "1.234,50", "1,234.50", "€ 150" e "150€".
    Rejeita negativos, NaN/infinito, notação científica, mais de duas casas
    decimais (por exemplo "1.234", que é ambíguo) e valores acima do limite
    aceito pelo PedidoService.
    """
    texto = (raw or "").strip().lower()
    for sufixo in _SUFIXOS_MOEDA:
        texto = texto.replace(sufixo, "")
    texto = re.sub(r"\s+", "", texto)
    if not _NUMERO.fullmatch(texto):
        return None

    if "," in texto and "." in texto:
        decimal_sep = "," if texto.rfind(",") > texto.rfind(".") else "."
        milhar_sep = "." if decimal_sep == "," else ","
        inteiro, _, fracao = texto.rpartition(decimal_sep)
        if not _milhares_validos(inteiro, milhar_sep):
            return None
        texto = inteiro.replace(milhar_sep, "") + "." + fracao
    elif "," in texto:
        if texto.count(",") > 1:
            return None
        texto = texto.replace(",", ".")
    elif texto.count(".") > 1:
        if not _milhares_validos(texto, "."):
            return None
        texto = texto.replace(".", "")

    try:
        valor = Decimal(texto)
    except InvalidOperation:
        return None
    if valor.as_tuple().exponent < -2:
        return None
    if valor < 0 or valor > VALOR_MAXIMO:
        return None
    return valor.quantize(Decimal("0.01"))


def _milhares_validos(inteiro: str, separador: str) -> bool:
    grupos = inteiro.split(separador)
    return (
        len(grupos) == 1
        or (1 <= len(grupos[0]) <= 3 and all(len(grupo) == 3 for grupo in grupos[1:]))
    )
