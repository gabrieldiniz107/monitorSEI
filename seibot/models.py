"""Dataclasses de domínio (puras, sem I/O)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


def normalizar_cnpj(doc: str) -> str:
    """Remove pontuação de CNPJ/CPF, deixando só dígitos (chave de join)."""
    return re.sub(r"\D", "", doc or "")


@dataclass(frozen=True)
class Intimacao:
    """Uma linha da tela 'Intimações Eletrônicas' (um par empresa+ofício)."""
    processo: str            # ex. "53500.050847/2026-16"
    doc_id: str              # ID interno do documento no SEI, ex. "15955558"
    oficio_desc: str         # ex. "Ofício 600"
    destinatario: str        # razão social / nome, ex. "Age Telecomunicações S.A"
    documento: str           # CNPJ/CPF já normalizado (só dígitos)
    documento_fmt: str       # CNPJ/CPF como exibido, ex. "36.230.547/0001-20"
    tipo_destinatario: str   # "Pessoa Jurídica" | "Pessoa Física"
    tipo_intimacao: str      # ex. "Comunica Decisão Administrativa de Cumprimento - URGENTE"
    data_expedicao: str      # como exibido, "dd/mm/aaaa"
    situacao: str            # "Pendente" | "Cumprida por Consulta Direta" | ...

    @property
    def prioridade_urgente(self) -> bool:
        return "URGENTE" in (self.tipo_intimacao or "").upper()

    @property
    def chave(self) -> str:
        """Chave de dedup: processo + documento(ofício) + CNPJ/CPF."""
        return f"{self.processo}|{self.doc_id}|{self.documento}"


@dataclass(frozen=True)
class Grupo:
    """Intimações de um mesmo ofício (doc_id) dentro de um processo.

    coletivo = mesmo ofício para várias empresas; individual = uma só.
    """
    processo: str
    doc_id: str
    oficio_desc: str
    tipo_intimacao: str
    data_expedicao: str
    situacao: str
    destinatarios: tuple[Intimacao, ...] = field(default_factory=tuple)

    @property
    def tipo(self) -> str:
        return "coletivo" if len(self.destinatarios) > 1 else "individual"

    @property
    def prioridade_urgente(self) -> bool:
        return any(i.prioridade_urgente for i in self.destinatarios)
