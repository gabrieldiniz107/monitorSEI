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
from urllib.parse import quote

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


def _url_path(caminho: str) -> str:
    """Escapa um caminho de drive para a URL (espaços e acentos são a regra nessas pastas).
    A barra continua sendo separador de pasta."""
    return quote(caminho.strip("/"), safe="/")


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

    def _post(self, url: str, json_body: dict, headers: dict | None = None) -> dict:
        """POST com retry/backoff em erros transitórios (429/5xx/timeout de rede).

        A criação de item é atômica no Graph: um 5xx significa (quase sempre) que nada foi
        gravado, então retentar é seguro. Como salvaguarda extra, quem cria o card checa a
        existência por Título antes (idempotente) — ver oficio_card.criar_card."""
        ultimo_erro = None
        for tentativa in range(1, _MAX_TENTATIVAS + 1):
            try:
                r = self._http.post(
                    url, json=json_body,
                    headers=self._hdr({"Content-Type": "application/json", **(headers or {})}))
            except httpx.HTTPError as e:
                ultimo_erro = e
            else:
                if r.status_code < 400:
                    return r.json()
                if r.status_code not in _RETRY_STATUS:
                    raise GraphError(f"POST {url} -> {r.status_code}: {r.text[:400]}")
                ultimo_erro = GraphError(f"POST {url} -> {r.status_code}: {r.text[:200]}")
            if tentativa < _MAX_TENTATIVAS:
                time.sleep(2 ** (tentativa - 1))
        raise GraphError(f"POST {url} falhou após {_MAX_TENTATIVAS} tentativas: {ultimo_erro}")

    def criar_item(self, lista_id: str, fields: dict) -> dict:
        """Cria um item na lista (POST). `fields` são os nomes INTERNOS das colunas
        (ex. Title, NumeroOficio, CNPJLookupId). Devolve o item criado (com `id`)."""
        url = f"{GRAPH}/sites/{self.site_id}/lists/{lista_id}/items"
        return self._post(url, {"fields": fields})

    # ------------------------------------------------------------------
    # Drive (biblioteca de documentos) — usado pela publicação dos ofícios coletivos
    # ------------------------------------------------------------------
    def _req_drive(self, metodo: str, url: str, *, ok_404: bool = False, **kw):
        """Request genérico com o mesmo retry/backoff de `_get`/`_post`.

        `ok_404` devolve None em vez de levantar — é como se pergunta "essa pasta existe?"
        sem precisar de um endpoint de busca.
        """
        ultimo_erro = None
        for tentativa in range(1, _MAX_TENTATIVAS + 1):
            try:
                r = self._http.request(metodo, url, **kw)
            except httpx.HTTPError as e:
                ultimo_erro = e
            else:
                if r.status_code == 404 and ok_404:
                    return None
                if r.status_code < 400:
                    return r.json() if r.content else {}
                if r.status_code not in _RETRY_STATUS:
                    raise GraphError(f"{metodo} {url} -> {r.status_code}: {r.text[:400]}")
                ultimo_erro = GraphError(f"{metodo} {url} -> {r.status_code}: {r.text[:200]}")
            if tentativa < _MAX_TENTATIVAS:
                time.sleep(2 ** (tentativa - 1))
        raise GraphError(f"{metodo} {url} falhou após {_MAX_TENTATIVAS} tentativas: {ultimo_erro}")

    def item_do_drive(self, drive_id: str, caminho: str) -> dict | None:
        """Item (arquivo ou pasta) pelo caminho relativo à raiz do drive. None se não existe."""
        return self._req_drive("GET", f"{GRAPH}/drives/{drive_id}/root:/{_url_path(caminho)}",
                               ok_404=True, headers=self._hdr())

    def garantir_pasta(self, drive_id: str, caminho_pai: str, nome: str) -> dict:
        """Devolve a pasta `caminho_pai/nome`, criando se não existir (idempotente)."""
        alvo = f"{caminho_pai}/{nome}" if caminho_pai else nome
        item = self.item_do_drive(drive_id, alvo)
        if item:
            return item
        url = (f"{GRAPH}/drives/{drive_id}/root:/{_url_path(caminho_pai)}:/children"
               if caminho_pai else f"{GRAPH}/drives/{drive_id}/root/children")
        corpo = {"name": nome, "folder": {}, "@microsoft.graph.conflictBehavior": "fail"}
        try:
            return self._req_drive("POST", url, json=corpo,
                                   headers=self._hdr({"Content-Type": "application/json"}))
        except GraphError:
            # corrida (ou 409 de "já existe"): se a pasta está lá agora, o objetivo foi atingido
            item = self.item_do_drive(drive_id, alvo)
            if item:
                return item
            raise

    def garantir_caminho(self, drive_id: str, caminho: str) -> dict:
        """Garante a árvore inteira `a/b/c`, nível a nível, e devolve a pasta final.

        `garantir_pasta` cria **um** nível e assume o pai existente — o que basta para a
        Fase 4, cuja raiz já existia. A Fase 5 estreia uma árvore nova, então precisa criar
        os níveis intermediários também.
        """
        pai, item = "", None
        for nome in [n for n in caminho.strip("/").split("/") if n]:
            item = self.garantir_pasta(drive_id, pai, nome)
            pai = f"{pai}/{nome}" if pai else nome
        if item is None:
            raise GraphError(f"caminho vazio: {caminho!r}")
        return item

    def upload_arquivo(self, drive_id: str, caminho: str, conteudo: bytes,
                       mime: str = "application/octet-stream") -> dict:
        """Sobe um arquivo (até ~4 MB) em `caminho`, relativo à raiz do drive.

        `conflictBehavior=replace` (e não `rename`) torna o comando **idempetente**: rodar
        de novo no mesmo ofício regrava os arquivos em vez de criar "Ofício (1).pdf".
        """
        url = (f"{GRAPH}/drives/{drive_id}/root:/{_url_path(caminho)}:/content"
               "?@microsoft.graph.conflictBehavior=replace")
        return self._req_drive("PUT", url, content=conteudo,
                               headers=self._hdr({"Content-Type": mime}))

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
