"""Mensagem DIRETA no Teams via Microsoft Graph com auth DELEGADA (device-code).

Porte do `automacaoVistorias/cft/src/teams_notify.py` (CFT/CREA) para este projeto — mesma
mecânica, mesmo app registration ("SCM VISTORIAS"), mesmos escopos.

**Por que delegada:** enviar mensagem de chat no Graph **não é suportado app-only**. Só um
token de usuário consegue `POST /chats` + `/chats/{id}/messages`. Por isso existe um login
device-code único, cujo refresh token fica em `state/.graph_token.json` (dentro do volume
`state/`, para sobreviver ao container).

Aqui o destinatário é o **responsável técnico** (`TEAMS_DEV_EMAIL`). Como o remetente é a
própria conta logada, se o e-mail for o mesmo da conta a lista colapsa para 1 membro — o
Graph recusa `oneOnOne` com 1 membro mas aceita `group` (self-chat), igual às vistorias.

PRÉ-REQUISITOS no app registration:
  - Permissões DELEGADAS `Chat.Create` + `ChatMessage.Send` + admin consent.
  - Authentication → "Allow public client flows" = Yes (necessário p/ device-code).

CLI:
  python -m seibot.teams_dm --login                 # login único (device-code)
  python -m seibot.teams_dm --teste "oi"            # manda uma DM de teste
  python -m seibot.teams_dm --token                 # confere escopos do token
"""
from __future__ import annotations

import base64
import json
import pathlib
import time
from typing import Optional

import httpx

GRAPH = "https://graph.microsoft.com/v1.0"
AUTHORITY = "https://login.microsoftonline.com"
SCOPE = ("https://graph.microsoft.com/Chat.Create "
         "https://graph.microsoft.com/ChatMessage.Send "
         "offline_access openid profile")


class TeamsDMError(RuntimeError):
    pass


# ---------------------------------------------------------------- token
def _cache_path(cfg) -> pathlib.Path:
    return pathlib.Path(getattr(cfg, "graph_token_cache", "") or "state/.graph_token.json")


def _chats_path(cfg) -> pathlib.Path:
    return pathlib.Path(getattr(cfg, "teams_chat_cache", "") or "state/.teams_chats.json")


def _salvar_token(cfg, body: dict) -> None:
    p = _cache_path(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"refresh_token": body.get("refresh_token")}))
    try:
        p.chmod(0o600)
    except OSError:
        pass


def _print_flush(*a):
    """O código do device-code precisa aparecer NA HORA; sob cron/pipe o stdout do
    Python é bufferizado e a mensagem só sairia no fim (inútil para um código com TTL)."""
    print(*a, flush=True)


def login_device_code(cfg, http: Optional[httpx.Client] = None, log=_print_flush) -> None:
    """Login único. Imprime o código, espera você autenticar e salva o refresh token."""
    http = http or httpx.Client(timeout=30)
    if not cfg.graph_tenant_id or not cfg.graph_client_id:
        raise TeamsDMError("Faltam GRAPH_TENANT_ID / GRAPH_CLIENT_ID no .env")
    r = http.post(f"{AUTHORITY}/{cfg.graph_tenant_id}/oauth2/v2.0/devicecode",
                  data={"client_id": cfg.graph_client_id, "scope": SCOPE})
    if r.status_code >= 400:
        raise TeamsDMError(f"devicecode -> {r.status_code}: {r.text[:400]}")
    d = r.json()
    log("\n" + "=" * 60)
    log(d.get("message")
        or f"Acesse {d['verification_uri']} e informe o código: {d['user_code']}")
    log("=" * 60 + "\n(aguardando login…)")

    intervalo = int(d.get("interval", 5))
    fim = time.time() + int(d.get("expires_in", 900))
    while time.time() < fim:
        time.sleep(intervalo)
        t = http.post(f"{AUTHORITY}/{cfg.graph_tenant_id}/oauth2/v2.0/token", data={
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "client_id": cfg.graph_client_id, "device_code": d["device_code"]})
        body = t.json()
        if t.status_code < 400:
            _salvar_token(cfg, body)
            log(f"✓ login concluído; refresh token em {_cache_path(cfg)}")
            return
        err = body.get("error")
        if err == "authorization_pending":
            continue
        if err == "slow_down":
            intervalo += 5
            continue
        raise TeamsDMError(
            f"token (device) -> {err}: {body.get('error_description', '')[:300]}")
    raise TeamsDMError("tempo de login esgotado; rode --login de novo.")


def token_graph(cfg, http: Optional[httpx.Client] = None) -> str:
    """Troca o refresh token salvo por um access token com escopos de Teams."""
    http = http or httpx.Client(timeout=30)
    p = _cache_path(cfg)
    if not p.exists():
        raise TeamsDMError(
            f"Sem login delegado ({p}): rode 'python -m seibot.teams_dm --login' uma vez.")
    rt = json.loads(p.read_text()).get("refresh_token")
    if not rt:
        raise TeamsDMError(f"refresh_token ausente em {p}; rode --login de novo.")
    r = http.post(f"{AUTHORITY}/{cfg.graph_tenant_id}/oauth2/v2.0/token", data={
        "grant_type": "refresh_token", "client_id": cfg.graph_client_id,
        "refresh_token": rt, "scope": SCOPE})
    if r.status_code >= 400:
        raise TeamsDMError(
            f"refresh Graph -> {r.status_code}: {r.text[:300]} "
            "(token pode ter expirado/sido revogado — rode --login de novo.)")
    body = r.json()
    if body.get("refresh_token"):   # rotaciona; persiste no mesmo cache
        _salvar_token(cfg, body)
    return body["access_token"]


def _claims(token: str) -> dict:
    """Payload do JWT (sem validar assinatura) — só p/ ler upn/scp."""
    p = token.split(".")[1]
    p += "=" * (-len(p) % 4)
    return json.loads(base64.urlsafe_b64decode(p))


def me_upn(token: str) -> str:
    c = _claims(token)
    upn = c.get("upn") or c.get("preferred_username")
    if not upn:
        raise TeamsDMError("não foi possível extrair o UPN do remetente do token.")
    return upn


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}",
            "Content-Type": "application/json", "Accept": "application/json"}


# ---------------------------------------------------------------- chat
def ordenado_unico(emails: list[str]) -> list[str]:
    """Dedup case-insensitive preservando a 1ª ocorrência."""
    visto, out = set(), []
    for e in emails:
        k = (e or "").strip().lower()
        if k and k not in visto:
            visto.add(k)
            out.append(e.strip())
    return out


def _chave(emails: list[str]) -> str:
    return "|".join(sorted(e.lower() for e in emails))


def _criar_chat(emails: list[str], token: str, http: httpx.Client) -> str:
    """2 membros = oneOnOne; 1 membro (self-chat) ou 3+ = group."""
    membros = [{
        "@odata.type": "#microsoft.graph.aadUserConversationMember",
        "roles": ["owner"],
        "user@odata.bind": f"{GRAPH}/users('{e}')",
    } for e in emails]
    body = {"chatType": "oneOnOne" if len(emails) == 2 else "group", "members": membros}
    r = http.post(f"{GRAPH}/chats", headers=_auth(token), json=body)
    if r.status_code >= 400:
        raise TeamsDMError(f"criar chat -> {r.status_code}: {r.text[:400]}")
    cid = r.json().get("id")
    if not cid:
        raise TeamsDMError(f"criar chat: resposta sem id ({r.text[:200]})")
    return cid


def garantir_chat(cfg, emails: list[str], token: str, http: httpx.Client,
                  *, forcar: bool = False) -> str:
    """chatId p/ o conjunto de membros, reusando o cache em disco.

    O Graph NÃO deduplica group chats — sem cache, cada execução criaria um chat novo.
    """
    p = _chats_path(cfg)
    cache = {}
    if p.exists():
        try:
            cache = json.loads(p.read_text())
        except (ValueError, OSError):
            cache = {}
    chave = _chave(emails)
    if not forcar and chave in cache:
        return cache[chave]
    cid = _criar_chat(emails, token, http)
    cache[chave] = cid
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cache, ensure_ascii=False))
    return cid


def _postar(chat_id: str, corpo_html: str, token: str, http: httpx.Client) -> httpx.Response:
    return http.post(f"{GRAPH}/chats/{chat_id}/messages", headers=_auth(token),
                     json={"body": {"contentType": "html", "content": corpo_html}})


# ---------------------------------------------------------------- envio
def enviar_dm(cfg, corpo_html: str, http: Optional[httpx.Client] = None) -> str:
    """Manda a mensagem ao TEAMS_DEV_EMAIL. Devolve o chat_id. Levanta TeamsDMError."""
    destino = (getattr(cfg, "teams_dev_email", "") or "").strip()
    if not destino:
        raise TeamsDMError("TEAMS_DEV_EMAIL não configurado no .env")
    http = http or httpx.Client(timeout=30)
    token = token_graph(cfg, http)
    membros = ordenado_unico([me_upn(token), destino])
    chat_id = garantir_chat(cfg, membros, token, http)
    r = _postar(chat_id, corpo_html, token, http)
    if r.status_code == 404:  # chat do cache sumiu → recria uma vez
        chat_id = garantir_chat(cfg, membros, token, http, forcar=True)
        r = _postar(chat_id, corpo_html, token, http)
    if r.status_code >= 400:
        raise TeamsDMError(f"postar mensagem -> {r.status_code}: {r.text[:400]}")
    return chat_id


def main(argv=None) -> int:
    import argparse

    from .config import load_config

    ap = argparse.ArgumentParser(prog="seibot.teams_dm",
                                 description="DM no Teams via Graph (auth delegada)")
    ap.add_argument("--login", action="store_true", help="login único via device-code")
    ap.add_argument("--token", action="store_true", help="confere os escopos do token")
    ap.add_argument("--teste", metavar="TEXTO", help="manda uma DM de teste")
    args = ap.parse_args(argv)

    cfg = load_config()
    if args.login:
        login_device_code(cfg)
        return 0
    if args.token:
        c = _claims(token_graph(cfg))
        print(f"upn : {c.get('upn') or c.get('preferred_username')}")
        print(f"scp : {c.get('scp')}")
        return 0
    if args.teste:
        import html as _h
        cid = enviar_dm(cfg, f"<b>[Teste monitorSEI]</b><br>{_h.escape(args.teste)}")
        print(f"✓ enviado (chat {cid}) para {cfg.teams_dev_email}")
        return 0
    ap.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
