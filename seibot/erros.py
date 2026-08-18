"""Notificação de erros no Teams — rede de segurança da execução automática.

Com a Fase 2 rodando sozinha no cron (e dando ciência, que inicia prazo legal), qualquer
falha precisa chegar em alguém. Erros vão para a **DM do responsável técnico**
(`TEAMS_DEV_EMAIL`, via Graph delegado — mesmo padrão do CFT/CREA em `automacaoVistorias`),
e não para o grupo do Jurídico: erro de automação é ruído para o time jurídico.

Ordem de destino (invertida em 18/08/2026, decisão do Gabriel):
  1. `TEAMS_WEBHOOK_ERROS_URL` → canal **AUTOMAÇÕES - ALERTAS**, via webhook do
     Workflows. É o destino preferido porque **não depende de token**.
  2. `TEAMS_DEV_EMAIL` → DM via `teams_dm.enviar_dm` (Graph delegado) — reserva, usada
     quando não há webhook ou quando o envio dele falha.
  3. nada configurado → só loga.

⚠️ Por que o webhook vem primeiro: a DM depende de um refresh token delegado
(`state/.graph_token.json`) que **expira** — e o canal de erro existe justamente para
avisar quando algo quebrou, inclusive o próprio token. Com o webhook na frente, a falha
do token continua sendo avisada. O mesmo raciocínio vale para os projetos irmãos
(automacaoColetas e automacaoVistorias), que usam este mesmo canal.

Regra de ouro daqui: **notificar erro NUNCA pode levantar exceção.** Se o envio falhar,
engole e loga — senão o alerta de falha vira uma segunda falha e o processo morre calado.
"""
from __future__ import annotations

import html as _html
import re
import traceback
from datetime import datetime
from typing import Optional

from .teams import enviar_payload, montar_card_erro

# limite defensivo: traceback gigante pode estourar o payload do fluxo
_MAX_TRACE = 2500


def _url_erros(cfg) -> str:
    """A URL do canal de alertas. NUNCA cai no webhook do grupo do Jurídico.

    Erro de automação é ruído para o time jurídico: se só houver
    `TEAMS_WEBHOOK_INTIMACOES_URL`, o certo é não notificar por webhook nenhum.
    """
    return (getattr(cfg, "teams_webhook_erros_url", "") or "").strip()


def formatar_erro(contexto: str, exc: BaseException, *,
                  detalhe: Optional[str] = None, critico: bool = False) -> str:
    """Mensagem HTML do erro (pura — testável)."""
    e = _html.escape
    trace = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    if len(trace) > _MAX_TRACE:
        trace = trace[:_MAX_TRACE] + "\n… (truncado)"
    linhas = [
        "🚨 <b>ERRO no monitorSEI</b>" if not critico
        else "🆘 <b>ERRO CRÍTICO no monitorSEI — AÇÃO MANUAL NECESSÁRIA</b>",
        f"<b>Onde:</b> {e(contexto)}",
        f"<b>Erro:</b> {e(type(exc).__name__)}: {e(str(exc))}",
    ]
    if detalhe:
        linhas.append(detalhe)  # já vem em HTML montado pelo chamador
    linhas.append(f"<pre>{e(trace)}</pre>")
    return "<br>".join(linhas)


def partes_do_erro(contexto: str, exc: BaseException, *,
                   detalhe: Optional[str] = None) -> tuple[list[str], str]:
    """(linhas, traceback) em TEXTO puro — para o card, que não renderiza HTML."""
    trace = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    if len(trace) > _MAX_TRACE:
        trace = trace[:_MAX_TRACE] + "\n… (truncado)"
    linhas = [f"Onde: {contexto}",
              f"Erro: {type(exc).__name__}: {exc}"]
    if detalhe:
        # o detalhe vem em HTML (montado para a DM); no card entra sem as tags
        limpo = re.sub(r"<br\s*/?>", " · ", detalhe)
        limpo = _html.unescape(re.sub(r"<[^>]+>", "", limpo)).strip()
        if limpo:
            linhas.append(limpo)
    return linhas, trace


def notificar_erro(cfg, contexto: str, exc: BaseException, *,
                   detalhe: Optional[str] = None, critico: bool = False, log=print) -> bool:
    """Avisa o erro no canal de alertas (webhook) ou, na falta dele, na DM.

    Devolve True se conseguiu avisar em algum canal. **NUNCA levanta**: avisar sobre um
    erro não pode virar um segundo erro que derruba o processo.
    """
    url = _url_erros(cfg)
    if url:
        titulo = ("ERRO CRÍTICO no monitorSEI — AÇÃO MANUAL NECESSÁRIA" if critico
                  else "ERRO no monitorSEI")
        linhas, trace = partes_do_erro(contexto, exc, detalhe=detalhe)
        quando = datetime.now().strftime("%d/%m/%Y %H:%M")
        try:
            enviar_payload(url, montar_card_erro(titulo, linhas, trace, critico,
                                                 quando=quando))
            return True
        except Exception as e:  # noqa: BLE001 — cai para a DM em vez de perder o aviso
            log(f"  ⚠️ falhou ao avisar o erro no canal do Teams: {e}")

    destino = (getattr(cfg, "teams_dev_email", "") or "").strip()
    if destino:
        corpo = formatar_erro(contexto, exc, detalhe=detalhe, critico=critico)
        try:
            from .teams_dm import enviar_dm
            enviar_dm(cfg, corpo)
            return True
        except Exception as e:  # noqa: BLE001 — avisar não pode derrubar o processo
            # bem alto: sem isso o alerta some e a falha original fica invisível
            log(f"  ⚠️⚠️ FALHOU ao mandar DM do erro para {destino}: {e}")
            log("       (token delegado pode ter expirado — rode "
                "'python -m seibot.teams_dm --login')")
            log(f"       erro original: {type(exc).__name__}: {exc}")

    if not url and not destino:
        log("  ⚠️ erro não notificado: nem TEAMS_WEBHOOK_ERROS_URL nem TEAMS_DEV_EMAIL.")
    return False
