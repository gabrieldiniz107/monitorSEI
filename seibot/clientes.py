"""Base de clientes (SharePoint Gestão Integrada) — cross-check por CNPJ.

Regra de "ativo" (decidida com o cruzamento das bases, 2026-07-15): **união** —
o cliente é ativo se `StatusContrato == "Ativo"` na lista **Clientes SCM** OU se
tem ao menos um contrato `Ativo` na lista **Comercial** (o campo da Clientes SCM
está desatualizado p/ ~132 clientes com contrato vivo). Também anota a adimplência
(lista **Financeiro**, campo `Situacao`).

Join SEI↔SharePoint por CNPJ (só dígitos). `Title` da Clientes SCM = CNPJ formatado.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Optional, Protocol

from . import graph

ATIVO = "ativo"
INATIVO = "inativo"

# colunas de e-mail na Clientes SCM (para o envio da Fase 2)
_EMAIL_COLS = ("field_3", "EmailFinanceiro", "EmailTecnico", "EmailAdm")
# vocabulário de Financeiro.Situacao
_INADIMPLENTE = {"Inadimplente 1 Parcela", "Inadimplente 2 Parcelas",
                 "Análise p/ Inclusão no SERASA", "Negativados SERASA"}
_ADIMPLENTE = {"Adimplentes", "Pagamento concluído", "Débito renegociado"}


def _dig(s: str | None) -> str:
    return re.sub(r"\D", "", s or "")


def _emails_de(fields: dict) -> tuple[str, ...]:
    out: list[str] = []
    for col in _EMAIL_COLS:
        for e in re.split(r"[,;\s]+", fields.get(col) or ""):
            e = e.strip().lower()
            if "@" in e and e not in out:
                out.append(e)
    return tuple(out)


@dataclass
class ClienteInfo:
    cnpj: str
    em_base: bool
    razao: str = ""
    status_raw: str = ""            # StatusContrato (Clientes SCM)
    contrato_ativo: bool = False    # tem contrato "Ativo" no Comercial
    adimplencia: Optional[str] = None       # 'adimplente' | 'inadimplente' | None
    adimplencia_detalhe: str = ""
    emails: tuple[str, ...] = ()

    @property
    def ativo(self) -> bool:
        return self.status_raw == "Ativo" or self.contrato_ativo

    @property
    def inadimplente(self) -> bool:
        """Só o inadimplente EXPLÍCITO conta. Cliente ativo sem registro no Financeiro
        (`adimplencia is None`, ~18% dos ativos) NÃO é tratado como inadimplente."""
        return self.adimplencia == "inadimplente"


def motivo_sem_tratativa(info: Optional[ClienteInfo]) -> Optional[str]:
    """Motivo para NÃO fazer a tratativa automática — `None` significa "pode tratar".

    Fonte ÚNICA da regra: usada tanto pela seleção de candidatos (`tratativa`) quanto pelo
    aviso ao Jurídico (`notify`), para as duas nunca divergirem. Tratativa automática dá
    CIÊNCIA (irreversível) ⇒ exige cliente **ativo e não-inadimplente** (decisão 2026-07-21).
    """
    if info is None:
        return "empresa fora da base de clientes"
    if not info.ativo:
        return f"cliente não-ativo ({info.status_raw or 'sem status'})"
    if info.inadimplente:
        det = f" ({info.adimplencia_detalhe})" if info.adimplencia_detalhe else ""
        return f"cliente INADIMPLENTE{det}"
    return None


class BaseClientes(Protocol):
    def status(self, cnpj: str) -> Optional[str]: ...
    def info(self, cnpj: str) -> Optional[ClienteInfo]: ...
    def emails(self, cnpj: str) -> list[str]: ...


class SharePointClientes:
    """Carrega Clientes SCM + Comercial + Financeiro e indexa por CNPJ."""

    def __init__(self, g=None, log=print):
        self._por_cnpj: dict[str, ClienteInfo] = {}
        self._g = g if g is not None else graph.cliente()
        self._log = log
        self._carregar()

    def _carregar(self) -> None:
        g = self._g
        id2cnpj: dict[str, str] = {}

        # 1) Clientes SCM: base cadastral (Title = CNPJ), status e e-mails
        for it in g.itens(graph.LISTA_CLIENTES_SCM, top=999):
            f = it.get("fields", {})
            cnpj = _dig(f.get("Title"))
            if not cnpj:
                continue
            id2cnpj[str(f.get("id"))] = cnpj
            self._por_cnpj[cnpj] = ClienteInfo(
                cnpj=cnpj, em_base=True,
                razao=(f.get("field_1") or "").strip(),
                status_raw=(f.get("StatusContrato") or "").strip(),
                emails=_emails_de(f),
            )

        # 2) Comercial: quem tem contrato "Ativo" (CNPJ é lookup p/ Clientes SCM)
        for it in g.itens(graph.LISTA_COMERCIAL, top=999):
            f = it.get("fields", {})
            cnpj = id2cnpj.get(str(f.get("CNPJLookupId") or ""))
            if cnpj and (f.get("StatusContrato") or "").strip() == "Ativo":
                info = self._por_cnpj.get(cnpj)
                if info:
                    info.contrato_ativo = True

        # 3) Financeiro: adimplência (Situacao), agregada por CNPJ
        situacoes: dict[str, set[str]] = {}
        for it in g.itens(graph.LISTA_FINANCEIRO, top=999):
            f = it.get("fields", {})
            cnpj = id2cnpj.get(str(f.get("CNPJLookupId") or ""))
            s = (f.get("Situacao") or "").strip()
            if cnpj and s:
                situacoes.setdefault(cnpj, set()).add(s)
        for cnpj, sits in situacoes.items():
            info = self._por_cnpj.get(cnpj)
            if not info:
                continue
            inad = sits & _INADIMPLENTE
            if inad:
                info.adimplencia = "inadimplente"
                info.adimplencia_detalhe = "; ".join(sorted(inad))
            elif sits & _ADIMPLENTE:
                info.adimplencia = "adimplente"

        self._log(f"→ SharePoint: {len(self._por_cnpj)} clientes indexados.")

    # ---- API (BaseClientes) ----
    def info(self, cnpj: str) -> Optional[ClienteInfo]:
        return self._por_cnpj.get(_dig(cnpj))

    def status(self, cnpj: str) -> Optional[str]:
        info = self.info(cnpj)
        if info is None:
            return None
        return ATIVO if info.ativo else INATIVO

    def emails(self, cnpj: str) -> list[str]:
        info = self.info(cnpj)
        return list(info.emails) if info else []


def sharepoint_configurado() -> bool:
    return all(os.environ.get(k) for k in
               ("GRAPH_TENANT_ID", "GRAPH_CLIENT_ID", "GRAPH_CLIENT_SECRET"))


def carregar_clientes(log=print) -> Optional[SharePointClientes]:
    """Fábrica tolerante: None se GRAPH_* ausente ou SharePoint indisponível
    (assim a Fase 1a segue funcionando sem o cross-check)."""
    if not sharepoint_configurado():
        log("  (SharePoint não configurado — seguindo sem cross-check de clientes)")
        return None
    try:
        return SharePointClientes(log=log)
    except Exception as e:
        log(f"  (aviso: SharePoint indisponível: {e})")
        return None
