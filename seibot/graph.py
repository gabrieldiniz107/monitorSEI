"""Microsoft Graph — cliente REST do SharePoint "Gestão Integrada" (genérico).

Cópia do módulo do projeto de vistorias (automacaoVistorias/common/graph.py),
autossuficiente (só depende de `httpx`). Autenticação app-only (client credentials)
com o app "SCM VISTORIAS": lê GRAPH_TENANT_ID / GRAPH_CLIENT_ID / GRAPH_CLIENT_SECRET
de `os.environ`. Requer a permissão de APLICAÇÃO Sites.ReadWrite.All (admin consent).

⚠️ Este módulo NÃO carrega `.env` — o chamador deve carregar antes de `cliente()`.
"""
from __future__ import annotations
import os
import time
from dataclasses import dataclass, field
from typing import Iterator

import httpx

_RETRY_STATUS = {429, 500, 502, 503, 504}
_MAX_TENTATIVAS = 4

GRAPH = "https://graph.microsoft.com/v1.0"
AUTHORITY = "https://login.microsoftonline.com"

HOSTNAME = "scmprovedor.sharepoint.com"
SITE_PATH = "/sites/GestaoIntegrada"
SITE_ID_COMPOSTO = (
    f"{HOSTNAME},84933a75-0ded-48e3-9e1d-e9566b83c6cd,"
    "416259aa-f290-46ee-951b-34369b85c1bb"
)

# GUIDs das listas do site (descobertos via g.listas())
LISTA_CLIENTES_SCM = "2f954b27-bd88-4afe-afba-9e8517c88cd8"   # base cadastral (Title = CNPJ)
LISTA_COMERCIAL = "07ecd0ee-ffb4-48a7-a212-1b8fe1690360"       # contratos (StatusContrato)
LISTA_FINANCEIRO = "58f1d8eb-ab5f-4106-a065-27ff034c39c4"      # adimplência (Situacao)


class GraphError(RuntimeError):
    pass


@dataclass
class GraphSharePoint:
    token: str
    site_id: str
    _http: httpx.Client = field(repr=False)

    def _hdr(self, extra: dict | None = None) -> dict:
        h = {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}
        if extra:
            h.update(extra)
        return h

    def _get(self, url: str, params: dict | None = None, headers: dict | None = None) -> dict:
        """GET com retry/backoff em erros transitórios (429/5xx/timeout de rede)."""
        ultimo_erro = None
        for tentativa in range(1, _MAX_TENTATIVAS + 1):
            try:
                r = self._http.get(url, params=params, headers=self._hdr(headers))
            except httpx.HTTPError as e:
                ultimo_erro = e
            else:
                if r.status_code < 400:
                    return r.json()
                if r.status_code not in _RETRY_STATUS:
                    raise GraphError(f"GET {url} -> {r.status_code}: {r.text[:400]}")
                ultimo_erro = GraphError(f"GET {url} -> {r.status_code}: {r.text[:200]}")
            if tentativa < _MAX_TENTATIVAS:
                time.sleep(2 ** (tentativa - 1))  # 1s, 2s, 4s
        raise GraphError(f"GET {url} falhou após {_MAX_TENTATIVAS} tentativas: {ultimo_erro}")

    def listas(self) -> list[dict]:
        url = f"{GRAPH}/sites/{self.site_id}/lists"
        data = self._get(url, params={"$select": "id,name,displayName,webUrl"})
        return data.get("value", [])

    def itens(self, lista_id: str, filtro: str | None = None,
              select_fields: str | None = None, top: int = 50,
              max_itens: int | None = None) -> Iterator[dict]:
        exp = "fields" if not select_fields else f"fields($select={select_fields})"
        params = {"$expand": exp, "$top": str(top)}
        # header "MayFailRandomly" só é necessário p/ $filter em coluna não indexada;
        # em listagem completa ele é dispensável e pode causar páginas incompletas.
        headers = None
        if filtro:
            params["$filter"] = filtro
            headers = {"Prefer": "HonorNonIndexedQueriesWarningMayFailRandomly"}
        url = f"{GRAPH}/sites/{self.site_id}/lists/{lista_id}/items"
        contados = 0
        while url:
            data = self._get(url, params=params, headers=headers)
            params = None
            for it in data.get("value", []):
                yield it
                contados += 1
                if max_itens and contados >= max_itens:
                    return
            url = data.get("@odata.nextLink")

    def buscar_item(self, lista_id: str, title: str) -> dict | None:
        f = f"fields/Title eq '{title}'"
        for it in self.itens(lista_id, filtro=f, top=1, max_itens=1):
            return it
        return None

    def colunas(self, lista_id: str) -> list[dict]:
        url = f"{GRAPH}/sites/{self.site_id}/lists/{lista_id}/columns"
        data = self._get(url, params={"$select": "name,displayName,hidden,readOnly"})
        return data.get("value", [])


def obter_token(tenant: str, client_id: str, secret: str, http: httpx.Client) -> str:
    r = http.post(
        f"{AUTHORITY}/{tenant}/oauth2/v2.0/token",
        data={
            "client_id": client_id,
            "client_secret": secret,
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials",
        },
    )
    if r.status_code >= 400:
        raise GraphError(f"token -> {r.status_code}: {r.text[:500]}")
    return r.json()["access_token"]


def _resolver_site_id(token: str, http: httpx.Client) -> str:
    hdr = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    url = f"{GRAPH}/sites/{HOSTNAME}:{SITE_PATH}"
    r = http.get(url, headers=hdr)
    if r.status_code < 400:
        return r.json()["id"]
    return SITE_ID_COMPOSTO


def cliente(timeout: float = 30.0) -> GraphSharePoint:
    tenant = os.environ.get("GRAPH_TENANT_ID")
    client_id = os.environ.get("GRAPH_CLIENT_ID")
    secret = os.environ.get("GRAPH_CLIENT_SECRET")
    faltando = [k for k, v in (
        ("GRAPH_TENANT_ID", tenant), ("GRAPH_CLIENT_ID", client_id),
        ("GRAPH_CLIENT_SECRET", secret)) if not v]
    if faltando:
        raise GraphError(f"Faltam variáveis no .env: {', '.join(faltando)}")
    http = httpx.Client(timeout=timeout)
    token = obter_token(tenant, client_id, secret, http)
    site_id = _resolver_site_id(token, http)
    return GraphSharePoint(token=token, site_id=site_id, _http=http)
