"""Regras de despejo compartilhadas por contentor, carrinha e backend legado."""


def divergencia_residuo_prompt(residuo_efetivo: str, residuo_contratado: str) -> str:
    return (
        f"O resíduo informado ({residuo_efetivo}) é diferente do contratado "
        f"para este equipamento ({residuo_contratado}).\n\n"
        "Descreva a divergência com pelo menos 10 caracteres."
    )
