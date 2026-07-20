"""Fase 2 / Increment 2 — resumo do ofício (OpenAI) para o corpo do e-mail ao cliente.

Seguro: só chama a API do LLM, não toca no SEI. O `client` é injetável (os testes usam
um fake, sem gastar API). O texto do ofício vem do SEI em HTML (ISO-8859-1) — `limpar()`
tira as tags e as entidades antes de mandar pro modelo.
"""
from __future__ import annotations

import html as _html
import re
from typing import Optional

from .config import Config

_SISTEMA = (
    "Você é assistente jurídico da SCM Engenharia, que representa provedores de internet "
    "perante a Anatel. Sua tarefa é resumir ofícios/intimações da Anatel de forma clara e "
    "objetiva para comunicar ao cliente. Escreva em português, com tom profissional e "
    "acessível. NÃO invente informações — baseie-se apenas no texto fornecido."
)


def limpar(texto_ou_html: str) -> str:
    """HTML/entidades → texto puro."""
    s = texto_ou_html or ""
    if "<" in s and ">" in s:
        s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", _html.unescape(s)).strip()


def montar_prompt(oficio_texto: str, anexos: Optional[list[str]] = None) -> str:
    partes = [
        "Resuma o ofício da Anatel abaixo em 1 a 2 parágrafos objetivos, destacando: "
        "(1) o que a Anatel está comunicando ou exigindo; (2) o que o cliente precisa fazer, "
        "se aplicável; (3) o prazo, se mencionado no texto. Não use saudação nem despedida — "
        "apenas o resumo.",
    ]
    if anexos:
        partes.append("Documentos anexos citados no ofício: " + "; ".join(anexos) + ".")
    partes.append("\nTEXTO DO OFÍCIO:\n" + limpar(oficio_texto))
    return "\n".join(partes)


def _client(cfg: Config):
    from openai import OpenAI
    if not cfg.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY não configurado no .env")
    return OpenAI(api_key=cfg.openai_api_key)


def resumir(
    oficio_texto: str,
    cfg: Config,
    *,
    anexos: Optional[list[str]] = None,
    client=None,
) -> str:
    """Gera o resumo do ofício para o e-mail. `client` injetável (testes)."""
    client = client or _client(cfg)
    resp = client.chat.completions.create(
        model=cfg.openai_model,
        temperature=0.2,
        messages=[
            {"role": "system", "content": _SISTEMA},
            {"role": "user", "content": montar_prompt(oficio_texto, anexos)},
        ],
    )
    return (resp.choices[0].message.content or "").strip()
