"""Notificação de erros no Teams — rede de segurança da execução automática.

Com a Fase 2 rodando sozinha no cron (e dando ciência, que inicia prazo legal), qualquer
falha precisa chegar em alguém. Erros vão para a **DM do responsável técnico**
(`TEAMS_DEV_EMAIL`, via Graph delegado — mesmo padrão do CFT/CREA em `automacaoVistorias`),
e não para o grupo do Jurídico: erro de automação é ruído para o time jurídico.

Ordem de destino:
  1. `TEAMS_DEV_EMAIL` → DM via `teams_dm.enviar_dm` (Graph delegado, device-code).
  2. `TEAMS_WEBHOOK_ERROS_URL` → webhook (só se não houver TEAMS_DEV_EMAIL).
  3. nada configurado → só loga.

⚠️ A DM depende de um refresh token delegado (`state/.graph_token.json`) que **expira**. Se
ele morrer, a DM falha e o erro fica só no log — por isso o fracasso do envio é logado bem
alto. Rodar `python -m seibot.teams_dm --token` de tempos em tempos para conferir.

Regra de ouro daqui: **notificar erro NUNCA pode levantar exceção.** Se o envio falhar,
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
    """Webhook de fallback — só quando não há TEAMS_DEV_EMAIL."""
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


def notificar_erro(cfg, contexto: str, exc: BaseException, *,
                   detalhe: Optional[str] = None, critico: bool = False, log=print) -> bool:
    """Manda o erro para a DM do responsável técnico. Devolve True se enviou. NUNCA levanta."""
    corpo = formatar_erro(contexto, exc, detalhe=detalhe, critico=critico)

    destino = (getattr(cfg, "teams_dev_email", "") or "").strip()
    if destino:
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

    url = _url_erros(cfg)
    if not url:
        if not destino:
            log("  ⚠️ erro não notificado: nem TEAMS_DEV_EMAIL nem TEAMS_WEBHOOK_ERROS_URL.")
        return False
    try:
        enviar_teams_webhook(url, corpo, getattr(cfg, "teams_webhook_style", "text"))
        return True
    except Exception as e:  # noqa: BLE001
        log(f"  ⚠️ falhou ao notificar erro no webhook: {e}")
        return False
