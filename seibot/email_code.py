"""Captura do código 2FA do SEI via IMAP (Gmail, somente leitura).

Fluxo: o bot dispara o login (que faz o SEI enviar um código novo por e-mail) e
então chama `esperar_codigo(apos=<instante do disparo>)`, que fica consultando o
IMAP até achar um e-mail do SEI recebido depois daquele instante, e extrai o código.

Adaptado do projeto scm-watchers (mesmo mecanismo, somente leitura, filtro por
remetente no servidor).
"""
from __future__ import annotations

import email
import imaplib
import re
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from email.message import Message
from email.utils import parsedate_to_datetime
from typing import Optional

# "código de acesso ... 123456" (4 a 8 dígitos; o SEI usa 6)
_MARKER = "codigo de acesso"
_TOKEN_RE = re.compile(r"c[oó]digo\s+de\s+acesso[^\d]{0,20}(\d{4,8})", re.IGNORECASE)
_HTML_TAG_RE = re.compile(r"<[^>]+>")

# Sem isso, uma conexão IMAP que trava (rede/DNS instável) fica pendurada para
# sempre — o timeout_s de esperar_codigo() nunca é alcançado porque ele conta
# entre tentativas, não dentro de uma chamada bloqueada (incidente 2026-08-19).
_IMAP_TIMEOUT_S = 20


def _sem_acento(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)
    ).lower()


def _to_text(body: str) -> str:
    if "<" in body and ">" in body:
        body = _HTML_TAG_RE.sub(" ", body)
        body = re.sub(r"&nbsp;?", " ", body)
        return re.sub(r"\s+", " ", body).strip()
    return body


def _body(msg: Message) -> str:
    plain, html = "", ""
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            if ctype not in ("text/plain", "text/html"):
                continue
            if part.get("Content-Disposition", "").startswith("attachment"):
                continue
            payload = part.get_payload(decode=True)
            if payload is None:
                continue
            charset = part.get_content_charset() or "utf-8"
            text = payload.decode(charset, errors="replace")
            plain += text if ctype == "text/plain" else ""
            html += text if ctype == "text/html" else ""
    else:
        payload = msg.get_payload(decode=True)
        if payload is not None:
            charset = msg.get_content_charset() or "utf-8"
            plain = payload.decode(charset, errors="replace")
    return plain or html


def _extrair_codigo(msg: Message) -> Optional[str]:
    corpo = _to_text(_body(msg))
    assunto = _to_text(msg.get("Subject", ""))
    if _MARKER not in _sem_acento(assunto + " " + corpo):
        return None
    m = _TOKEN_RE.search(corpo) or _TOKEN_RE.search(assunto)
    return m.group(1) if m else None


def _buscar_uma_vez(cfg, apos: datetime) -> Optional[str]:
    """Retorna o código do e-mail do SEI mais recente recebido depois de `apos`."""
    since_date = (apos - timedelta(days=1)).strftime("%d-%b-%Y")  # SINCE = granularidade de dia
    conn = imaplib.IMAP4_SSL(cfg.imap_host, cfg.imap_port, timeout=_IMAP_TIMEOUT_S)
    achados: list[tuple[datetime, str]] = []
    try:
        conn.login(cfg.imap_user, cfg.imap_app_password)
        conn.select("INBOX", readonly=True)
        typ, data = conn.search(None, "FROM", f'"{cfg.sei_code_from}"', "SINCE", since_date)
        if typ != "OK" or not data or not data[0]:
            return None
        for num in data[0].split():
            typ, msg_data = conn.fetch(num, "(RFC822)")
            if typ != "OK" or not msg_data or not msg_data[0]:
                continue
            msg = email.message_from_bytes(msg_data[0][1])
            try:
                received = parsedate_to_datetime(msg.get("Date"))
            except Exception:
                continue
            if received.tzinfo is None:
                received = received.replace(tzinfo=timezone.utc)
            if received < apos:
                continue
            codigo = _extrair_codigo(msg)
            if codigo:
                achados.append((received.astimezone(timezone.utc), codigo))
    finally:
        try:
            conn.logout()
        except Exception:
            pass
    if not achados:
        return None
    achados.sort(key=lambda x: x[0], reverse=True)
    return achados[0][1]


def esperar_codigo(cfg, apos: datetime, timeout_s: int = 120, intervalo_s: int = 5, log=lambda *a: None) -> str:
    """Espera o código 2FA chegar (recebido depois de `apos`). Erro se estourar o timeout.

    `apos` deve ser o instante (UTC) imediatamente ANTERIOR ao clique de login, com uma
    pequena folga de tolerância de relógio já aplicada pelo chamador.

    Falha de rede/IMAP numa tentativa (timeout, conexão recusada, etc.) não aborta na
    hora — é tratada como "ainda não achou" e tenta de novo até estourar `timeout_s`,
    já que agora cada tentativa individual tem seu próprio timeout (`_IMAP_TIMEOUT_S`).
    """
    limite = time.monotonic() + timeout_s
    tentativa = 0
    while time.monotonic() < limite:
        tentativa += 1
        try:
            codigo = _buscar_uma_vez(cfg, apos)
        except Exception as exc:
            log(f"  (aviso IMAP tentativa {tentativa}: {exc})")
            codigo = None
        if codigo:
            return codigo
        time.sleep(intervalo_s)
    raise TimeoutError(
        f"Código 2FA do SEI não chegou em {timeout_s}s (remetente={cfg.sei_code_from}, "
        f"após={apos.isoformat()})."
    )
