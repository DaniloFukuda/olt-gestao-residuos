from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import os
from pathlib import Path
import sys
from typing import Iterable

from sqlalchemy.orm import Session

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.db import SessionLocal
from app.core.phone import normalize_phone
from app.models.operador import Operador, PerfilOperador
from app.repositories.operador_repository import OperadorRepository


@dataclass(frozen=True)
class GestorCadastro:
    telefone: str
    nome: str


class EstadoCadastro(StrEnum):
    CRIADO = "CRIADO"
    ATUALIZADO = "ATUALIZADO"
    JA_ESTAVA_CORRETO = "JÁ ESTAVA CORRETO"


@dataclass(frozen=True)
class ResultadoCadastro:
    telefone: str
    nome: str
    estado: EstadoCadastro


# Telefones e nomes são dados pessoais e o repositório é público: os gestores
# vêm dos argumentos ou de OLT_GESTORES, nunca do código.
USO = (
    "Uso: python scripts/cadastrar_gestores_lucas_secretario.py "
    '"351XXXXXXXXX:Nome do Gestor" ["351XXXXXXXXX:Outro Gestor" ...]\n'
    'ou defina OLT_GESTORES="351XXXXXXXXX:Nome;351XXXXXXXXX:Outro" no ambiente.'
)


def parse_gestores(valores: Iterable[str]) -> tuple[GestorCadastro, ...]:
    gestores = []
    for valor in valores:
        telefone, separador, nome = valor.partition(":")
        if not separador or not telefone.strip() or not nome.strip():
            raise ValueError(f"Gestor inválido (esperado telefone:nome): {valor!r}")
        gestores.append(GestorCadastro(telefone=telefone.strip(), nome=nome.strip()))
    return tuple(gestores)


def cadastrar_gestores(
    db: Session,
    gestores: Iterable[GestorCadastro],
) -> list[ResultadoCadastro]:
    repository = OperadorRepository(db)
    resultados: list[ResultadoCadastro] = []

    with db.begin():
        for cadastro in gestores:
            telefone = normalize_phone(cadastro.telefone)
            if not telefone:
                raise ValueError("Telefone de gestor inválido")

            operador = repository.get_by_telefone(telefone)
            if operador is None:
                operador = Operador(
                    telefone_whatsapp=telefone,
                    nome_operador=cadastro.nome,
                    perfil=PerfilOperador.GESTOR,
                    ativo=True,
                )
                db.add(operador)
                estado = EstadoCadastro.CRIADO
            else:
                alterado = (
                    operador.nome_operador != cadastro.nome
                    or operador.perfil != PerfilOperador.GESTOR
                    or operador.ativo is not True
                )
                operador.nome_operador = cadastro.nome
                operador.perfil = PerfilOperador.GESTOR
                operador.ativo = True
                estado = EstadoCadastro.ATUALIZADO if alterado else EstadoCadastro.JA_ESTAVA_CORRETO

            db.flush()
            resultados.append(
                ResultadoCadastro(
                    telefone=telefone,
                    nome=cadastro.nome,
                    estado=estado,
                )
            )

    return resultados


def main(argv: list[str] | None = None) -> int:
    valores = sys.argv[1:] if argv is None else argv
    if not valores:
        valores = [item for item in os.environ.get("OLT_GESTORES", "").split(";") if item.strip()]
    try:
        gestores = parse_gestores(valores)
    except ValueError as exc:
        print(f"ERRO: {exc}\n{USO}")
        return 2
    if not gestores:
        print(USO)
        return 2
    try:
        with SessionLocal() as db:
            resultados = cadastrar_gestores(db, gestores)
    except Exception as exc:
        print(f"ERRO: cadastro de gestores revertido: {type(exc).__name__}")
        return 1

    for resultado in resultados:
        print(f"{resultado.telefone} | {resultado.nome} | {resultado.estado}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
