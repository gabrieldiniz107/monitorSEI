"""Comentário em item de lista (SharePoint REST) — auth DELEGADA.

Porte de `automacaoVistorias/cft/src/sharepoint_comments.py` (a automação do CREA/CFT).
Motivo de ser separado do `graph.py` (que é app-only):
- Comentário de item **não existe no Microsoft Graph**; só na REST do SharePoint
  (`_api/web/lists(guid'..')/items(id)/Comments`).
- Essa API é **delegada por natureza**: o comentário tem um usuário autor → token app-only
  (sem usuário) é rejeitado (401). Por isso usamos um token de usuário.

**Reaproveita o MESMO login device-code do `teams_dm`** (refresh token em
`state/.graph_token.json`): validado ao vivo (2026-07-22) que ele redime para o escopo do
SharePoint (`AllSites.Write`, `aud`=SharePoint Online). Um login só cobre a DM de erro (Graph)
e o comentário (SharePoint) — **não precisa de um segundo `--login`**.

Pré-requisito no app "SCM VISTORIAS": permissão DELEGADA SharePoint **AllSites.Write** + admin
consent (já existe — as vistorias usam) e "Allow public client flows" = Yes.
"""
from __future__ import annotations

import json
from datetime import date
from typing import Optional

import httpx

from . import graph as _graph
from .teams_dm import _cache_path, _salvar_token  # mesmo cache do login device-code

AUTHORITY = "https://login.microsoftonline.com"
HOSTNAME = _graph.HOSTNAME          # scmprovedor.sharepoint.com
SITE_PATH = _graph.SITE_PATH        # /sites/GestaoIntegrada
SITE_BASE = f"https://{HOSTNAME}{SITE_PATH}"
SCOPE = f"https://{HOSTNAME}/AllSites.Write offline_access openid profile"


class ComentarioError(RuntimeError):
    pass


def token_sharepoint(cfg, http: Optional[httpx.Client] = None) -> str:
    """Troca o refresh token salvo (o do teams_dm) por um access token da REST do SharePoint."""
    http = http or httpx.Client(timeout=30)
    p = _cache_path(cfg)
    if not p.exists():
        raise ComentarioError(
            f"Sem login delegado ({p}): rode 'python -m seibot.teams_dm --login' uma vez.")
    rt = json.loads(p.read_text()).get("refresh_token")
    if not rt:
        raise ComentarioError(f"refresh_token ausente em {p}; rode --login de novo.")
    r = http.post(f"{AUTHORITY}/{cfg.graph_tenant_id}/oauth2/v2.0/token", data={
        "grant_type": "refresh_token", "client_id": cfg.graph_client_id,
        "refresh_token": rt, "scope": SCOPE})
    if r.status_code >= 400:
        raise ComentarioError(
            f"refresh SharePoint -> {r.status_code}: {r.text[:300]} "
            "(token pode ter expirado/sido revogado — rode 'python -m seibot.teams_dm --login').")
    body = r.json()
    if body.get("refresh_token"):   # rotaciona; persiste no mesmo cache compartilhado
        _salvar_token(cfg, body)
    return body["access_token"]


def postar_comentario(cfg, lista_id: str, item_id, texto: str,
                      http: Optional[httpx.Client] = None) -> dict:
    """Posta um comentário no item da lista (autor = usuário logado). Levanta ComentarioError."""
    http = http or httpx.Client(timeout=30)
    token = token_sharepoint(cfg, http)
    url = f"{SITE_BASE}/_api/web/lists(guid'{lista_id}')/items({item_id})/Comments"
    r = http.post(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/json;odata=nometadata",
        "Content-Type": "application/json",
    }, json={"text": texto})
    if r.status_code >= 400:
        raise ComentarioError(f"POST comment -> {r.status_code}: {r.text[:400]}")
    return r.json() if r.text else {}


def texto_card(grupo, hoje: Optional[date] = None) -> str:
    """Comentário que marca o card como gerado pela automação (padrão do CREA/CFT)."""
    d = (hoje or date.today()).strftime("%d/%m/%Y")
    return (f"[Automação Jurídico] 🤖 Card criado automaticamente pelo monitor do SEI em {d}, "
            f"a partir da intimação eletrônica ({grupo.oficio_desc}, processo {grupo.processo}). "
            "Os campos de andamento (Status, Tipo de Ofício, etc.) devem ser preenchidos pela equipe.")
