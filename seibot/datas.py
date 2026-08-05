"""Datas — dia útil e conversões do formato do SEI. Puro, sem I/O.

Centralizado porque "dia útil" é usado em dois lugares com pesos bem diferentes:
- **Ciência** (`monitor._cmd_tratar`): o bot não pode dar ciência em fim de semana —
  iniciar prazo legal fora de dia útil é decisão do Jurídico, não da automação.
- **Acompanhamento de prazos** (`prazos.py`): a cadência dos lembretes é em dias
  corridos (decisão do usuário), mas o aviso em si só faz sentido em dia útil.

⚠️ **Feriados não são considerados** — só sábado e domingo. Uma tabela de feriados
nacionais (e municipais, que também suspendem prazo) precisaria ser mantida à mão e
erraria silenciosamente quando desatualizasse. Enquanto não houver essa fonte, o bot
pode dar ciência num feriado. Ver "Pontos abertos" no CLAUDE.md.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

_SABADO, _DOMINGO = 5, 6


def eh_dia_util(d: date) -> bool:
    """Segunda a sexta. Não considera feriados (ver aviso no topo do módulo)."""
    return d.weekday() not in (_SABADO, _DOMINGO)


def proximo_dia_util(d: date) -> date:
    while not eh_dia_util(d):
        d += timedelta(days=1)
    return d


def de_ddmmaaaa(s: str) -> Optional[date]:
    """'19/08/2026' -> date. None se vazio ou malformado (o SEI às vezes não traz prazo)."""
    try:
        return datetime.strptime((s or "").strip(), "%d/%m/%Y").date()
    except ValueError:
        return None


def para_ddmmaaaa(d: date) -> str:
    return d.strftime("%d/%m/%Y")
