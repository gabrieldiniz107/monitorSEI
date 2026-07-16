"""Fase 2 / Increment 4 — montagem e envio do rascunho de e-mail ao cliente.

O bot monta a mensagem no formato do Microsoft Graph (assunto, corpo HTML, destinatários
e anexos em base64) e faz POST no fluxo do Power Automate, que cria o RASCUNHO na caixa do
Jurídico (`juridico@`) para a equipe revisar e enviar. Partes puras são testáveis.
"""
from __future__ import annotations

import base64
import html as _html
import json
import urllib.request
from typing import Optional

from .processo import Prazo

_ODATA_ANEXO = "#microsoft.graph.fileAttachment"
_ASSINATURA = "Atenciosamente,<br><b>Departamento Jurídico — SCM Engenharia</b>"


def montar_assunto(oficio_desc: str, doc_id: str, processo: str) -> str:
    return f"Anatel — {oficio_desc} (SEI nº {doc_id}) — Processo {processo}"


def montar_corpo_html(
    empresa: str,
    processo: str,
    oficio_desc: str,
    doc_id: str,
    resumo: str,
    prazo: Optional[Prazo] = None,
    tem_anexos: bool = False,
) -> str:
    e = _html.escape
    linhas = [
        f"<p>Prezados(as), {e(empresa)},</p>",
        f"<p>A Anatel emitiu, no processo {e(processo)}, o {e(oficio_desc)} "
        f"(SEI nº {e(doc_id)}), cujo teor resumimos abaixo:</p>",
        f"<p>{e(resumo)}</p>",
    ]
    if prazo is not None:
        linhas.append(
            f"<p><b>Prazo:</b> resposta até <b>{e(prazo.data_limite)}</b> "
            f"({e(prazo.tipo)}, {prazo.dias} dias).</p>"
        )
    docs = "o ofício e os documentos relacionados" if tem_anexos else "o ofício"
    linhas.append(
        f"<p>Segue em anexo {docs}. Ficamos à disposição para orientá-los quanto "
        "às providências.</p>"
    )
    linhas.append(f"<p>{_ASSINATURA}</p>")
    return "\n".join(linhas)


def _anexo_graph(nome: str, conteudo: bytes) -> dict:
    return {
        "@odata.type": _ODATA_ANEXO,
        "name": nome,
        "contentBytes": base64.b64encode(conteudo).decode("ascii"),
    }


def montar_mensagem_graph(
    destinatarios: list[str],
    assunto: str,
    corpo_html: str,
    anexos: Optional[list[tuple[str, bytes]]] = None,
) -> dict:
    """Mensagem no formato do Graph (POST /me/messages cria rascunho)."""
    msg = {
        "subject": assunto,
        "body": {"contentType": "HTML", "content": corpo_html},
        "toRecipients": [{"emailAddress": {"address": a}} for a in destinatarios if a],
    }
    if anexos:
        msg["attachments"] = [_anexo_graph(n, c) for n, c in anexos]
    return msg


def criar_rascunho(url: str, mensagem: dict, timeout: int = 30) -> None:
    """POST da mensagem ao fluxo do Power Automate (cria o rascunho no Jurídico)."""
    data = json.dumps(mensagem).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        if resp.status >= 300:
            corpo = resp.read().decode(errors="replace")
            raise RuntimeError(f"Webhook do rascunho retornou HTTP {resp.status}: {corpo}")
