from app.integrations.whatsapp.client import send_whatsapp_message
from app.integrations.whatsapp.parser import parse_whatsapp_payload


def _options_body(count: int) -> str:
    lines = ["Escolha uma opção:"]
    lines.extend(f"{index}. Opção {index}" for index in range(1, count + 1))
    return "\n".join(lines)


def test_whatsapp_message_with_two_options_uses_buttons():
    result = send_whatsapp_message("351900000000", _options_body(2), force_mock=True)

    assert result["type"] == "interactive"
    assert result["interactive_type"] == "button"
    assert result["body"] == "Escolha uma opção:"
    assert result["buttons"] == [
        {"id": "option_1", "title": "Opção 1"},
        {"id": "option_2", "title": "Opção 2"},
    ]


def test_whatsapp_message_with_three_options_uses_buttons():
    result = send_whatsapp_message("351900000000", _options_body(3), force_mock=True)

    assert result["interactive_type"] == "button"
    assert [button["id"] for button in result["buttons"]] == ["option_1", "option_2", "option_3"]


def test_whatsapp_message_with_four_options_uses_list():
    result = send_whatsapp_message("351900000000", _options_body(4), force_mock=True)

    assert result["type"] == "interactive"
    assert result["interactive_type"] == "list"
    assert result["body"] == "Escolha uma opção:"
    assert [row["id"] for row in result["list_rows"]] == [
        "option_1",
        "option_2",
        "option_3",
        "option_4",
    ]


def test_whatsapp_message_with_five_options_uses_list():
    result = send_whatsapp_message("351900000000", _options_body(5), force_mock=True)

    assert result["interactive_type"] == "list"
    assert result["list_rows"][4] == {"id": "option_5", "title": "Opção 5"}


def test_whatsapp_message_with_six_to_ten_options_uses_one_list():
    # Regra de UX: o utilizador escolhe, não digita. A lista da Meta aceita 10 linhas.
    for count in (6, 10):
        result = send_whatsapp_message("351900000000", _options_body(count), force_mock=True)

        assert result["interactive_type"] == "list"
        assert result["body"] == "Escolha uma opção:"
        assert [row["id"] for row in result["list_rows"]] == [f"option_{n}" for n in range(1, count + 1)]
        assert "additional_messages" not in result


def test_whatsapp_message_with_more_than_ten_options_uses_lists_in_sequence():
    result = send_whatsapp_message("351900000000", _options_body(23), force_mock=True)

    seguintes = result["additional_messages"]
    # Divididas por igual: 8 + 8 + 7 (nenhuma lista com uma linha só).
    assert [len(result["list_rows"])] + [len(parte["list_rows"]) for parte in seguintes] == [8, 8, 7]
    assert seguintes[0]["body"] == "Mais opções (9–16):"
    assert seguintes[1]["list_rows"][-1]["id"] == "option_23"


def test_options_after_a_numbered_summary_use_only_the_last_block():
    body = (
        "Confirme a entrega preparada:\n\n"
        "1. 📦 Contentor 1 | identificação: 3 | fotos: 1\n"
        "2. 📦 Contentor 2 | identificação: 4 | fotos: 1\n"
        "Pagamento: pendente\n\n"
        "1. ✅ Confirmar entrega\n"
        "2. ❌ Cancelar"
    )

    result = send_whatsapp_message("351900000000", body, force_mock=True)

    assert result["interactive_type"] == "button"
    assert [b["title"] for b in result["buttons"]] == ["✅ Confirmar entrega", "❌ Cancelar"]
    assert "1. 📦 Contentor 1" in result["body"]
    assert "Confirmar entrega" not in result["body"]


def test_long_body_goes_first_as_text_and_options_follow():
    resumo = "Linha do resumo do pedido\n" * 60
    body = resumo + "\n1. Confirmar\n2. Cancelar"

    result = send_whatsapp_message("351900000000", body, force_mock=True)

    assert result["previous_message"]["body"] == resumo.strip()
    assert result["body"] == "Escolha uma opção:"
    assert result["interactive_type"] == "button"


def test_parser_converts_button_option_id_to_number():
    messages = parse_whatsapp_payload(
        {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messages": [
                                    {
                                        "from": "351900000000",
                                        "id": "m1",
                                        "type": "interactive",
                                        "interactive": {
                                            "button_reply": {"id": "option_1", "title": "Opção 1"}
                                        },
                                    }
                                ]
                            }
                        }
                    ]
                }
            ]
        }
    )

    assert messages[0].texto == "1"


def test_parser_converts_list_option_id_to_number():
    messages = parse_whatsapp_payload(
        {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messages": [
                                    {
                                        "from": "351900000000",
                                        "id": "m1",
                                        "type": "interactive",
                                        "interactive": {
                                            "list_reply": {"id": "option_4", "title": "Opção 4"}
                                        },
                                    }
                                ]
                            }
                        }
                    ]
                }
            ]
        }
    )

    assert messages[0].texto == "4"
