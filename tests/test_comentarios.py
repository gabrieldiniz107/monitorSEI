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


# --- Fase 5: comentário da minuta de dilação ---
def test_comentario_da_minuta_registra_links_lacunas_e_o_que_nao_muda():
    linha = {"processo": "53500.109311/2026-14", "data_limite": "16/09/2026"}
    txt = comentarios.texto_minuta_dilacao(
        linha, "https://sp/minuta.docx", "https://sp/pasta",
        ("data da ciência",), 30, date(2026, 8, 18))

    assert "PEDIDO DE DILAÇÃO DE PRAZO" in txt and "18/08/2026" in txt
    assert "requerendo 30 dia(s)" in txt and "16/09/2026" in txt
    assert "1 lacuna(s)" in txt and "data da ciência" in txt and "[PREENCHER" in txt
    assert "https://sp/minuta.docx" in txt and "https://sp/pasta" in txt
    # o card NÃO sai da raia: isso encerraria o acompanhamento do prazo
    assert "não suspende nem interrompe" in txt
    assert "Aguardando documentação (cliente)" in txt


def test_comentario_da_minuta_sem_lacunas_nao_alarma():
    txt = comentarios.texto_minuta_dilacao({"data_limite": "16/09/2026"},
                                           "https://sp/x.docx", hoje=date(2026, 8, 18))
    assert "lacuna" not in txt and "Pasta" not in txt
