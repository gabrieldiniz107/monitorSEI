"""Testes das partes puras de montagem do rascunho (Increment 4)."""
import base64

from seibot.processo import Prazo
from seibot.rascunho import (montar_assunto, montar_corpo_html,
                             montar_mensagem_graph)


def test_assunto():
    a = montar_assunto("Ofício 1105", "15829514", "53500.049978/2026-42")
    assert "Ofício 1105" in a and "15829514" in a and "53500.049978/2026-42" in a


def test_corpo_com_prazo_e_anexos():
    prazo = Prazo(tipo="Defesa Preliminar", dias=15, data_limite="30/07/2026")
    html = montar_corpo_html("Goncalves Ltda", "53500.049978/2026-42", "Ofício 1105",
                             "15829514", "Resumo do teor.", prazo=prazo, tem_anexos=True)
    assert "Prezados(as), Goncalves Ltda" in html
    assert "Resumo do teor." in html
    assert "30/07/2026" in html and "15 dias" in html
    assert "documentos relacionados" in html
    assert "Departamento Jurídico" in html


def test_corpo_sem_prazo_sem_anexos():
    html = montar_corpo_html("X Ltda", "P", "Ofício 1", "999", "Resumo.",
                             prazo=None, tem_anexos=False)
    assert "Prazo:" not in html
    assert "Segue em anexo o ofício." in html


def test_corpo_escapa_html():
    html = montar_corpo_html("A & B Ltda", "P", "Ofício 1", "999", "resumo", None, False)
    assert "A &amp; B Ltda" in html


def test_mensagem_graph_com_anexos():
    msg = montar_mensagem_graph(
        ["a@x.com", "b@x.com"], "Assunto", "<p>corpo</p>",
        anexos=[("oficio.pdf", b"%PDF-1.4 conteudo"), ("ata.pdf", b"xyz")])
    assert msg["subject"] == "Assunto"
    assert msg["body"] == {"contentType": "HTML", "content": "<p>corpo</p>"}
    assert [r["emailAddress"]["address"] for r in msg["toRecipients"]] == ["a@x.com", "b@x.com"]
    assert len(msg["attachments"]) == 2
    an = msg["attachments"][0]
    assert an["@odata.type"] == "#microsoft.graph.fileAttachment"
    assert an["name"] == "oficio.pdf"
    assert base64.b64decode(an["contentBytes"]) == b"%PDF-1.4 conteudo"


def test_mensagem_graph_sem_anexos_nao_tem_attachments():
    msg = montar_mensagem_graph(["a@x.com"], "S", "<p>c</p>")
    assert "attachments" not in msg


def test_mensagem_graph_ignora_email_vazio():
    msg = montar_mensagem_graph(["a@x.com", "", None], "S", "c")
    assert len(msg["toRecipients"]) == 1
