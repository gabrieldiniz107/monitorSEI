"""Envio para o Teams via webhook (Power Automate/Workflows ou Incoming Webhook).

Cópia do padrão do projeto irmão scm-watchers — sem Azure Bot, só urllib stdlib.
"""
from __future__ import annotations

import json
import urllib.request


def montar_payload(mensagem: str, style: str = "text") -> dict:
    """style='text' (fluxo Power Automate lendo triggerBody()?['text']) ou
    'card' (Adaptive Card v1.4)."""
    if style == "card":
        return {
            "type": "message",
            "attachments": [{
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": {
                    "type": "AdaptiveCard",
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "version": "1.4",
                    "body": [{"type": "TextBlock", "text": mensagem, "wrap": True}],
                },
            }],
        }
    return {"text": mensagem}


def montar_card_erro(titulo: str, linhas: list[str], trace: str = "",
                     critico: bool = False, quando: str = "") -> dict:
    """Adaptive Card de ERRO para o canal de alertas.

    Leva a MESMA informação de sempre (onde, tipo, mensagem e traceback), só que
    legível: um resumo em FactSet, a linha final do traceback em destaque — que é a que
    quase sempre diz o que houve — e o traceback inteiro embaixo, em monoespaçado.

    ⚠️ Card **não renderiza HTML**, só markdown limitado: por isso nada de tags aqui.
    Também não se usa botão/ToggleVisibility, que nem sempre renderiza em mensagem
    postada por webhook — esconder o traceback atrás de um botão que não aparece seria
    perder justamente o que importa.
    """
    fatos = []
    for linha in linhas:
        rotulo, _, valor = linha.partition(":")
        if valor.strip():
            fatos.append({"title": rotulo.strip() + ":", "value": valor.strip()})
        else:
            fatos.append({"title": "Detalhe:", "value": linha})
    if quando:
        fatos.append({"title": "Quando:", "value": quando})

    corpo: list[dict] = [{
        "type": "TextBlock",
        "text": ("🆘 " if critico else "🚨 ") + titulo,
        "weight": "Bolder", "size": "Medium", "wrap": True, "color": "attention",
    }]
    if fatos:
        corpo.append({"type": "FactSet", "facts": fatos})

    ultima = ""
    for linha in reversed((trace or "").strip().splitlines()):
        if linha.strip():
            ultima = linha.strip()
            break
    if ultima:
        corpo.append({"type": "TextBlock", "text": ultima, "wrap": True,
                      "weight": "Bolder", "color": "attention", "spacing": "Medium"})
    if trace:
        corpo.append({"type": "TextBlock", "text": "Traceback completo:",
                      "size": "Small", "isSubtle": True, "spacing": "Medium"})
        corpo.append({"type": "TextBlock", "wrap": True, "fontType": "Monospace",
                      "size": "Small", "spacing": "None", "text": trace})
    corpo.append({"type": "TextBlock", "size": "Small", "isSubtle": True, "wrap": True,
                  "spacing": "Medium",
                  "text": "monitorSEI · canal técnico (o Jurídico não recebe isto)"})
    return {"type": "message",
            "attachments": [{
                "contentType": "application/vnd.microsoft.card.adaptive",
                "contentUrl": None,
                "content": {
                    "type": "AdaptiveCard",
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "version": "1.4", "body": corpo}}]}


def enviar_payload(url: str, payload: dict, timeout: int = 15) -> None:
    """POST de um payload já montado (usado pelo card de erro)."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        if resp.status >= 300:
            corpo = resp.read().decode(errors="replace")
            raise RuntimeError(f"Webhook do Teams retornou HTTP {resp.status}: {corpo}")


def enviar_teams_webhook(url: str, mensagem: str, style: str = "text", timeout: int = 15) -> None:
    enviar_payload(url, montar_payload(mensagem, style), timeout)
