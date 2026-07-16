"""Fase 2 — seleção de candidatos à tratativa individual.

Um candidato é um grupo **individual** (um ofício para uma empresa), cujo cliente é
**ATIVO** (SharePoint) e cuja Situação é **Pendente** (ainda sem ciência). Só esses
seguem para a tratativa (abrir → ciência → prazo → ofício/anexos → resumo → e-mail).

⚠️ Esta seleção é PURA (não abre nada). Abrir/dar ciência é responsabilidade do
executor da tratativa, atrás de comando/flag separado — nunca no `run` de produção.
"""
from __future__ import annotations

from typing import Optional

from .clientes import BaseClientes
from .models import Grupo

SITUACAO_PENDENTE = "Pendente"


def eh_candidato(g: Grupo, clientes: Optional[BaseClientes]) -> bool:
    if g.tipo != "individual":
        return False
    intim = g.destinatarios[0]
    if intim.situacao != SITUACAO_PENDENTE:
        return False
    if clientes is None:
        return False  # sem base não dá p/ afirmar que é ativo → não trata
    info = clientes.info(intim.documento)
    return info is not None and info.ativo


def selecionar_candidatos(grupos: list[Grupo], clientes: Optional[BaseClientes]) -> list[Grupo]:
    """Grupos individuais + cliente ATIVO + Situação Pendente."""
    return [g for g in grupos if eh_candidato(g, clientes)]
