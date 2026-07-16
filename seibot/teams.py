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


def enviar_teams_webhook(url: str, mensagem: str, style: str = "text", timeout: int = 15) -> None:
    data = json.dumps(montar_payload(mensagem, style)).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        if resp.status >= 300:
            corpo = resp.read().decode(errors="replace")
            raise RuntimeError(f"Webhook do Teams retornou HTTP {resp.status}: {corpo}")
