"""Teste do texto do comentário de automação (parte pura de comentarios.py)."""
from datetime import date

from seibot import comentarios
from seibot.models import Grupo


def _grupo():
    return Grupo(processo="53500.064050/2024-26", doc_id="15843941", oficio_desc="Ofício 407",
                 tipo_intimacao="Requerimento de Informações", data_expedicao="21/07/2026",
                 situacao="Cumprida por Consulta Direta", destinatarios=())


def test_texto_card_marca_automacao_com_data_e_referencias():
    t = comentarios.texto_card(_grupo(), hoje=date(2026, 7, 22))
    assert "[Automação Jurídico]" in t
    assert "22/07/2026" in t
    assert "Ofício 407" in t
    assert "53500.064050/2024-26" in t
