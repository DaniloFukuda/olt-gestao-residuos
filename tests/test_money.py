from decimal import Decimal

import pytest

from app.core.money import parse_valor_monetario


@pytest.mark.parametrize(
    ("raw", "esperado"),
    [
        ("150", "150.00"),
        ("150,5", "150.50"),
        ("150.50", "150.50"),
        ("1.234,50", "1234.50"),
        ("1,234.50", "1234.50"),
        ("1.234.567", "1234567.00"),
        ("450€", "450.00"),
        ("€ 450", "450.00"),
        ("450 EUR", "450.00"),
        ("450 euros", "450.00"),
        (" 1 234,50 € ", "1234.50"),
        ("0,00", "0.00"),
        ("99999999.99", "99999999.99"),
    ],
)
def test_parse_valor_monetario_aceita_formatos_portugueses(raw, esperado):
    assert parse_valor_monetario(raw) == Decimal(esperado)


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        "abc",
        "-50",
        "-0,01",
        "nan",
        "NaN",
        "inf",
        "infinity",
        "1e12",
        "1.234",
        "1,234",
        "12.5.0",
        "1,2,3",
        "10,999",
        "100000000",
        "1.234,56.7",
    ],
)
def test_parse_valor_monetario_rejeita_valores_invalidos_ou_ambiguos(raw):
    assert parse_valor_monetario(raw) is None
