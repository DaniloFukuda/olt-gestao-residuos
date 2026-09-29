import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.models.operador import Operador, PerfilOperador
from app.services.operador_service import OperadorService
from scripts.cadastrar_gestores_lucas_secretario import (
    EstadoCadastro,
    GestorCadastro,
    cadastrar_gestores,
    main,
    parse_gestores,
)


GESTORES = (
    GestorCadastro(telefone="351900000081", nome="Gestor Um"),
    GestorCadastro(telefone="351900000082", nome="Gestor Dois"),
)


TELEFONES = {gestor.telefone for gestor in GESTORES}


def _operadores_alvo(db_session) -> list[Operador]:
    return list(
        db_session.scalars(
            select(Operador)
            .where(Operador.telefone_whatsapp.in_(TELEFONES))
            .order_by(Operador.telefone_whatsapp)
        )
    )


def test_cadastra_os_dois_contatos_como_gestores_ativos_e_normalizados(db_session):
    resultados = cadastrar_gestores(db_session, GESTORES)

    assert [resultado.estado for resultado in resultados] == [
        EstadoCadastro.CRIADO,
        EstadoCadastro.CRIADO,
    ]
    operadores = _operadores_alvo(db_session)
    assert {operador.telefone_whatsapp for operador in operadores} == TELEFONES
    assert all(operador.perfil == PerfilOperador.GESTOR for operador in operadores)
    assert all(operador.ativo is True for operador in operadores)


def test_execucao_repetida_e_idempotente(db_session):
    cadastrar_gestores(db_session, GESTORES)

    resultados = cadastrar_gestores(db_session, GESTORES)

    assert all(resultado.estado == EstadoCadastro.JA_ESTAVA_CORRETO for resultado in resultados)
    quantidade = db_session.scalar(
        select(func.count()).select_from(Operador).where(Operador.telefone_whatsapp.in_(TELEFONES))
    )
    assert quantidade == 2


def test_atualiza_funcionario_inativo_e_preserva_outro_operador(db_session):
    existente = Operador(
        telefone_whatsapp="351900000081",
        nome_operador="Nome anterior",
        perfil=PerfilOperador.FUNCIONARIO,
        ativo=False,
    )
    outro = Operador(
        telefone_whatsapp="351900000099",
        nome_operador="Outro operador",
        perfil=PerfilOperador.FUNCIONARIO,
        ativo=False,
    )
    db_session.add_all([existente, outro])
    db_session.commit()

    resultados = cadastrar_gestores(db_session, GESTORES)

    assert resultados[0].estado == EstadoCadastro.ATUALIZADO
    db_session.refresh(existente)
    db_session.refresh(outro)
    assert (existente.nome_operador, existente.perfil, existente.ativo) == (
        "Gestor Um",
        PerfilOperador.GESTOR,
        True,
    )
    assert (outro.nome_operador, outro.perfil, outro.ativo) == (
        "Outro operador",
        PerfilOperador.FUNCIONARIO,
        False,
    )


def test_falha_no_segundo_cadastro_reverte_toda_a_transacao(db_session):
    gestores_invalidos = (
        GestorCadastro(telefone="+351 900 000 081", nome="Gestor Um"),
        GestorCadastro(telefone="351900000082", nome=None),  # type: ignore[arg-type]
    )

    with pytest.raises(IntegrityError):
        cadastrar_gestores(db_session, gestores_invalidos)

    assert db_session.scalar(select(func.count()).select_from(Operador)) == 0


def test_permissoes_sao_de_gestor_sem_fallback_do_env(db_session, monkeypatch):
    monkeypatch.setenv("WHATSAPP_OWNER_PHONE", "")
    monkeypatch.setenv("OWNER_WHATSAPP", "")
    monkeypatch.setenv("AUTHORIZED_OPERATOR_PHONE", "")
    monkeypatch.setenv("AUTHORIZED_OPERATOR_PHONES", "")
    cadastrar_gestores(db_session, GESTORES)

    decisoes = [OperadorService(db_session).decidir_acesso(telefone) for telefone in TELEFONES]

    assert all(decisao.autorizado is True for decisao in decisoes)
    assert all(decisao.perfil == PerfilOperador.GESTOR for decisao in decisoes)
    assert all(decisao.origem == "TABELA" for decisao in decisoes)


def test_script_nao_contem_telefones_fixos():
    from pathlib import Path
    import re

    fonte = Path("scripts/cadastrar_gestores_lucas_secretario.py").read_text(encoding="utf-8")

    assert not re.search(r"\b3519\d{8}\b", fonte)


def test_parse_gestores_aceita_telefone_e_nome():
    assert parse_gestores([" +351 900 000 081 : Gestor Um ", "351900000082:Gestor Dois"]) == (
        GestorCadastro(telefone="+351 900 000 081", nome="Gestor Um"),
        GestorCadastro(telefone="351900000082", nome="Gestor Dois"),
    )


@pytest.mark.parametrize("valor", ["351900000081", ":Nome", "351900000081:", "  "])
def test_parse_gestores_rejeita_entrada_incompleta(valor):
    with pytest.raises(ValueError):
        parse_gestores([valor])


def test_main_sem_gestores_configurados_nao_altera_nada(monkeypatch, capsys):
    monkeypatch.delenv("OLT_GESTORES", raising=False)

    assert main([]) == 2
    assert "OLT_GESTORES" in capsys.readouterr().out
