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
# colunas de telefone na Clientes SCM (para o card do ofício — texto livre, não fragmentar)
_TELEFONE_COLS = ("field_4", "TelefoneFinanceiro", "TelefoneTecnico", "TelefoneAdm")
# "Pacote" do cliente = o tier do contrato (coluna Servicos da lista Comercial, multi-choice).
# Ranking p/ desempate quando o cliente tem >1 tier ativo (~5% dos casos): prefere o maior
# tier de CONECTIVIDADE; JURÍDICO só entra se não houver nenhum (é como os cards manuais estão).
# ⚠️ Ordem BLACK>ULTRA>FLEX>LIGHT é um palpite — ajustar aqui se o Jurídico definir diferente.
_TIERS_RANK = {"BLACK": 4, "ULTRA": 3, "FLEX": 2, "LIGHT": 1, "JURÍDICO": 0}
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


def _telefones_de(fields: dict) -> tuple[str, ...]:
    """Telefones das colunas da Clientes SCM. Valor é texto livre já formatado
    (ex. '(35) 99940-4274', '33-33151084/33-98818-5640') — não fragmentar; só dedup."""
    out: list[str] = []
    for col in _TELEFONE_COLS:
        v = (fields.get(col) or "").strip()
        if v and v not in out:
            out.append(v)
    return tuple(out)


def _como_lista(v) -> list:
    """Campo multi-choice do Graph vem como lista; single como str. Normaliza p/ lista."""
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def _melhor_pacote(tiers: set) -> str:
    """Escolhe UM pacote entre os tiers ativos do cliente (ver _TIERS_RANK)."""
    return max(tiers, key=lambda t: _TIERS_RANK.get(t, -1)) if tiers else ""


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
    telefones: tuple[str, ...] = ()
    sp_item_id: str = ""            # id do item na lista Clientes SCM (alvo do lookup CNPJ)
    pacote: str = ""               # tier do contrato ativo (Comercial.Servicos), p/ o card

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
                telefones=_telefones_de(f),
                sp_item_id=str(f.get("id") or ""),
            )

        # 2) Comercial: quem tem contrato "Ativo" (CNPJ é lookup p/ Clientes SCM) + o tier
        #    do pacote (coluna Servicos, multi-choice), agregado por CNPJ p/ o card do ofício.
        tiers_ativos: dict[str, set] = {}
        for it in g.itens(graph.LISTA_COMERCIAL, top=999):
            f = it.get("fields", {})
            cnpj = id2cnpj.get(str(f.get("CNPJLookupId") or ""))
            if not cnpj or (f.get("StatusContrato") or "").strip() != "Ativo":
                continue
            info = self._por_cnpj.get(cnpj)
            if info:
                info.contrato_ativo = True
            for serv in _como_lista(f.get("Servicos")):
                s = (serv or "").strip()
                if s in _TIERS_RANK:
                    tiers_ativos.setdefault(cnpj, set()).add(s)
        for cnpj, tiers in tiers_ativos.items():
            info = self._por_cnpj.get(cnpj)
            if info:
                info.pacote = _melhor_pacote(tiers)

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
    @property
    def graph(self):
        """Cliente Graph subjacente (para quem precisa ESCREVER no site, ex. card do ofício)."""
        return self._g

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
