"""Formatação e envio das notificações de grupo para o Teams.

Dois formatos: `formatar_grupo` (texto puro, p/ dry-run/console e testes) e
`formatar_grupo_html` (o que vai pro Teams — o fluxo do Power Automate posta como
HTML, então usamos <b>/<br>/• para não virar "texto corrido").
"""
from __future__ import annotations

import html as _html
from typing import Optional

from .clientes import BaseClientes
from .models import Grupo, Intimacao
from .teams import enviar_teams_webhook


def _esc(s: object) -> str:
    return _html.escape(str(s), quote=False)

# quantas empresas listar por extenso num grupo coletivo antes de resumir "(+X)"
MAX_EMPRESAS_LISTADAS = 15


def _anotacao_status(intim: Intimacao, clientes: Optional[BaseClientes]) -> str:
    """Sufixo por empresa conforme SharePoint (Fase 1b). Vazio se sem base."""
    if clientes is None:
        return ""
    info = clientes.info(intim.documento)
    if info is None:
        return " (fora da base)"
    partes = []
    if info.ativo:
        partes.append("✅ ativo")
    else:
        rotulo = info.status_raw or "sem status"
        partes.append(f"⚠️ não-ativo ({rotulo})")
    if info.adimplencia == "inadimplente":
        partes.append(f"💰 inadimplente ({info.adimplencia_detalhe})"
                      if info.adimplencia_detalhe else "💰 inadimplente")
    elif info.adimplencia == "adimplente":
        partes.append("adimplente")
    return " — " + " · ".join(partes)


def _linha_empresa(intim: Intimacao, clientes: Optional[BaseClientes]) -> str:
    return f"{intim.destinatario} — {intim.documento_fmt}{_anotacao_status(intim, clientes)}"


def _motivo_nao_ativo(intim: Intimacao, clientes: BaseClientes) -> str:
    """Motivo pelo qual NÃO segue a tratativa individual (para o Jurídico)."""
    info = clientes.info(intim.documento)
    if info is None:
        return "empresa fora da base de clientes"
    return f"cliente não-ativo ({info.status_raw or 'sem status'})"


def _decisao_individual(intim: Intimacao, clientes: Optional[BaseClientes]) -> Optional[str]:
    """Linha de decisão da tratativa individual. None se sem base p/ decidir."""
    if clientes is None:
        return None
    info = clientes.info(intim.documento)
    if info is not None and info.ativo:
        return "▶️ Cliente ATIVO — seguir com a tratativa individual (abrir, prazo, ofício, e-mail)."
    return ("⛔ Sem tratativa automática — apenas ciência ao Jurídico. "
            f"Motivo: {_motivo_nao_ativo(intim, clientes)}.")


def formatar_grupo(g: Grupo, clientes: Optional[BaseClientes] = None) -> str:
    urgente = g.prioridade_urgente
    sino = "🔴" if urgente else "🔔"
    tipo_txt = g.tipo_intimacao + (" ⚠️ URGENTE" if urgente else "")

    linhas = [
        f"{sino} Nova intimação SEI ({g.tipo}"
        + (f" — {len(g.destinatarios)} empresas)" if g.tipo == "coletivo" else ")"),
        f"Processo: {g.processo}",
        f"Ofício: {g.oficio_desc} ({g.doc_id})",
        f"Tipo: {tipo_txt}",
        f"Expedição: {g.data_expedicao} | Situação: {g.situacao}",
    ]

    if g.tipo == "individual":
        intim = g.destinatarios[0]
        linhas.append(f"Empresa: {_linha_empresa(intim, clientes)}")
        decisao = _decisao_individual(intim, clientes)
        if decisao:
            linhas.append(decisao)
    else:
        mostrados = g.destinatarios[:MAX_EMPRESAS_LISTADAS]
        resto = len(g.destinatarios) - len(mostrados)
        linhas.append("Empresas:")
        linhas.extend(f"  • {_linha_empresa(i, clientes)}" for i in mostrados)
        if resto > 0:
            linhas.append(f"  • (+{resto} empresa(s))")
        # coletivo: só avisar; destacar quantas não estão ativas
        if clientes is not None:
            nao_ativas = sum(1 for i in g.destinatarios
                             if (clientes.info(i.documento) is None
                                 or not clientes.info(i.documento).ativo))
            if nao_ativas:
                linhas.append(f"⚠️ {nao_ativas} de {len(g.destinatarios)} empresa(s) "
                              "não-ativa(s)/fora da base.")

    return "\n".join(linhas)


def formatar_grupo_html(g: Grupo, clientes: Optional[BaseClientes] = None) -> str:
    """Versão HTML (para o Teams): negrito nos rótulos, quebras com <br>, marcadores."""
    urgente = g.prioridade_urgente
    sino = "🔴" if urgente else "🔔"
    tipo_txt = _esc(g.tipo_intimacao) + (" — ⚠️ <b>URGENTE</b>" if urgente else "")

    titulo = (f"{sino} <b>Nova intimação SEI</b> — {g.tipo}"
              + (f" ({len(g.destinatarios)} empresas)" if g.tipo == "coletivo" else ""))
    linhas = [
        titulo,
        f"<b>Processo:</b> {_esc(g.processo)}",
        f"<b>Ofício:</b> {_esc(g.oficio_desc)} ({_esc(g.doc_id)})",
        f"<b>Tipo:</b> {tipo_txt}",
        f"<b>Expedição:</b> {_esc(g.data_expedicao)} &nbsp;|&nbsp; "
        f"<b>Situação:</b> {_esc(g.situacao)}",
    ]

    if g.tipo == "individual":
        intim = g.destinatarios[0]
        linhas.append(f"<b>Empresa:</b> {_esc(_linha_empresa(intim, clientes))}")
        decisao = _decisao_individual(intim, clientes)
        corpo = "<br>".join(linhas)
        if decisao:
            corpo += f"<br><br><b>{_esc(decisao)}</b>"
        return corpo

    mostrados = g.destinatarios[:MAX_EMPRESAS_LISTADAS]
    resto = len(g.destinatarios) - len(mostrados)
    linhas.append("<b>Empresas:</b>")
    linhas.extend(f"• {_esc(_linha_empresa(i, clientes))}" for i in mostrados)
    if resto > 0:
        linhas.append(f"• (+{resto} empresa(s))")
    corpo = "<br>".join(linhas)
    if clientes is not None:
        nao_ativas = sum(1 for i in g.destinatarios
                         if (clientes.info(i.documento) is None
                             or not clientes.info(i.documento).ativo))
        if nao_ativas:
            corpo += (f"<br><br><b>⚠️ {nao_ativas} de {len(g.destinatarios)} "
                      "empresa(s) não-ativa(s)/fora da base.</b>")
    return corpo


def enviar_grupo(
    url: str,
    g: Grupo,
    style: str = "text",
    clientes: Optional[BaseClientes] = None,
    timeout: int = 15,
) -> None:
    # style 'card' = Adaptive Card (texto puro dentro). Caso padrão ('text'): o fluxo
    # posta como HTML, então mandamos HTML formatado.
    if style == "card":
        enviar_teams_webhook(url, formatar_grupo(g, clientes), "card", timeout)
    else:
        enviar_teams_webhook(url, formatar_grupo_html(g, clientes), "text", timeout)
