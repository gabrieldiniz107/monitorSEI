"""Notificação de erros no Teams — rede de segurança da execução automática.

Com a Fase 2 rodando sozinha no cron (e dando ciência, que inicia prazo legal), qualquer
falha precisa chegar em alguém. Este módulo manda o traceback para o Teams do responsável
técnico (`TEAMS_WEBHOOK_ERROS_URL`), caindo no webhook do grupo se o específico não estiver
configurado.

Regra de ouro daqui: **notificar erro NUNCA pode levantar exceção.** Se o webhook falhar,
engole e loga — senão o alerta de falha vira uma segunda falha e o processo morre calado.
"""
from __future__ import annotations

import html as _html
import traceback
from typing import Optional

from .teams import enviar_teams_webhook

# limite defensivo: traceback gigante pode estourar o payload do fluxo
_MAX_TRACE = 2500


def _url_erros(cfg) -> str:
    return (getattr(cfg, "teams_webhook_erros_url", "") or "").strip() or \
        (getattr(cfg, "teams_webhook_url", "") or "").strip()


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


def notificar_erro(cfg, contexto: str, exc: BaseException, *,
                   detalhe: Optional[str] = None, critico: bool = False, log=print) -> bool:
    """Manda o erro ao Teams. Devolve True se enviou. NUNCA levanta."""
    url = _url_erros(cfg)
    if not url:
        log("  ⚠️ erro não notificado: nenhum webhook de erros configurado.")
        return False
    try:
        enviar_teams_webhook(
            url, formatar_erro(contexto, exc, detalhe=detalhe, critico=critico),
            getattr(cfg, "teams_webhook_style", "text"))
        return True
    except Exception as e:  # noqa: BLE001 — falha ao avisar não pode derrubar o processo
        log(f"  ⚠️ falhou ao notificar erro no Teams: {e}")
        return False
