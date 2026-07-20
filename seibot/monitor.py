"""Orquestrador do monitor de Intimações + CLI.

Comandos:
  run       — login → raspar (com janela) → detectar novos → notificar no Teams.
  baseline  — raspar TUDO (sem janela) e marcar como visto SEM notificar. Rodar 1x no deploy.
  dry-run   — mostra o que seria notificado, sem tocar o banco nem o Teams.

Padrão de injeção de dependência (page/store/enviar/clientes) espelha o service.py do
scm-watchers → testável com fakes. "Marcar só após enviar com sucesso" → retry no próximo cron.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from typing import Callable

from . import classificar, clientes as clientes_mod, intimacoes, notify
from .config import Config, load_config
from .models import Grupo
from .store import IntimacoesStore


def _data_key(d: str):
    try:
        return datetime.strptime(d, "%d/%m/%Y").date()
    except Exception:
        return date.min


def executar(
    cfg: Config,
    *,
    page,
    store: IntimacoesStore,
    enviar: Callable[[Grupo], None],
    paginas: int = 1,
    log=print,
) -> dict:
    intims = intimacoes.coletar(page, cfg, paginas=paginas, log=log)
    grupos = classificar.agrupar_por_oficio(intims)
    novos = [g for g in grupos if any(not store.ja_visto(i.chave) for i in g.destinatarios)]

    # página cheia + quase tudo novo (fora do 1º baseline) ⇒ pode haver transbordo
    # além das linhas raspadas. Alerta para revisar a cadência / nº de páginas.
    if len(intims) >= 100 * paginas and store.contar() > 0 and len(novos) == len(grupos) and grupos:
        log("⚠️ Página cheia e todos os grupos são novos — pode haver intimações "
            "além das raspadas. Considere aumentar INTIMACOES_RUN_PAGINAS ou a cadência.")

    # guarda anti-massa: banco vazio + muitos novos = provável falta de baseline
    if store.contar() == 0 and len(novos) > cfg.seed_max:
        msg = (f"{len(novos)} grupos novos com banco vazio (>{cfg.seed_max}). "
               f"Rode 'baseline' antes do 'run' para não notificar em massa.")
        log("⚠️ " + msg)
        return {"status": "abortado_seed", "coletados": len(intims),
                "grupos": len(grupos), "novos": len(novos), "erro": msg}

    novos.sort(key=lambda g: _data_key(g.data_expedicao))
    notificados = falhas = 0
    for g in novos:
        try:
            enviar(g)
        except Exception as e:  # não marca → retry no próximo ciclo
            falhas += 1
            log(f"  erro ao notificar ofício {g.doc_id}: {e}")
            continue
        for i in g.destinatarios:
            store.marcar_visto(i, g.tipo)
        notificados += 1

    return {"status": "ok" if falhas == 0 else "parcial",
            "coletados": len(intims), "grupos": len(grupos),
            "novos": len(novos), "notificados": notificados, "falhas": falhas}


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------
def _cmd_run(cfg: Config) -> dict:
    from .login import fazer_login
    if not cfg.teams_webhook_url:
        return {"status": "erro", "erro": "TEAMS_WEBHOOK_INTIMACOES_URL não configurado."}
    store = IntimacoesStore(cfg.seen_db_path)
    clientes = clientes_mod.carregar_clientes()
    enviar = lambda g: notify.enviar_grupo(  # noqa: E731
        cfg.teams_webhook_url, g, cfg.teams_webhook_style, clientes=clientes)
    with fazer_login(cfg) as sess:
        return executar(cfg, page=sess.page, store=store, enviar=enviar,
                        paginas=cfg.run_paginas)


def _cmd_baseline(cfg: Config) -> dict:
    from .login import fazer_login
    store = IntimacoesStore(cfg.seen_db_path)
    with fazer_login(cfg) as sess:
        intims = intimacoes.coletar(sess.page, cfg, paginas=cfg.baseline_paginas)
        n = store.marcar_lote(intims)
    return {"status": "ok", "coletados": len(intims), "marcados": n, "no_banco": store.contar()}


def _cmd_dry_run(cfg: Config) -> dict:
    from .login import fazer_login
    store = IntimacoesStore(cfg.seen_db_path)
    with fazer_login(cfg) as sess:
        intims = intimacoes.coletar(sess.page, cfg, paginas=cfg.run_paginas)
    grupos = classificar.agrupar_por_oficio(intims)
    novos = [g for g in grupos if any(not store.ja_visto(i.chave) for i in g.destinatarios)]
    clientes = clientes_mod.carregar_clientes()
    print(f"\n===== DRY-RUN: {len(novos)} grupo(s) que seriam notificados =====")
    for g in novos:
        print("\n" + notify.formatar_grupo(g, clientes))
    return {"status": "ok", "coletados": len(intims), "grupos": len(grupos), "novos": len(novos)}


def _cmd_tratar(cfg: Config, modo: str = "ensaio", processo_alvo: str | None = None) -> dict:
    """Fase 2 — tratativa individual, em 3 modos:
    - ensaio (default): só LISTA candidatos (individual+ativo+Pendente). NÃO abre nada.
    - completo <--processo P>: ENSAIO GERAL num processo JÁ CUMPRIDO (Situação != Pendente):
      roda todo o pipeline e CRIA um rascunho de verdade, SEM dar ciência nova. Valida tudo.
    - real: trata os PENDENTES de verdade → **DÁ CIÊNCIA** (inicia prazo). Cria rascunho.
    """
    from . import sessao, tratativa
    clientes = clientes_mod.carregar_clientes()
    store = IntimacoesStore(cfg.seen_db_path)

    with sessao.abrir(cfg, permitir_login=True) as sess:
        intims = intimacoes.coletar(sess.page, cfg, paginas=cfg.run_paginas)
        grupos = classificar.agrupar_por_oficio(intims)

        if modo == "ensaio":
            candidatos = tratativa.selecionar_candidatos(grupos, clientes)
            print(f"\n===== TRATAR (ENSAIO): {len(candidatos)} candidato(s) — NADA foi aberto =====")
            for g in candidatos:
                i = g.destinatarios[0]
                print(f"  • {g.processo} | {g.oficio_desc} ({g.doc_id}) | {i.destinatario} — "
                      f"{i.documento_fmt} | {g.tipo_intimacao}")
            return {"status": "ok", "modo": "ensaio", "coletados": len(intims),
                    "candidatos": len(candidatos)}

        if modo == "completo":
            if not processo_alvo:
                return {"status": "erro", "erro": "modo completo exige --processo <nº>."}
            g = next((x for x in grupos if x.processo == processo_alvo and x.tipo == "individual"), None)
            if g is None:
                return {"status": "erro", "erro": f"processo individual {processo_alvo} não achado na página."}
            if g.situacao == "Pendente":
                return {"status": "erro",
                        "erro": "ABORTADO: processo Pendente — o ensaio-completo só roda em já cumprido (não dar ciência)."}
            print(f"\n===== TRATAR (ENSAIO-COMPLETO) em {processo_alvo} (Situação: {g.situacao}) =====")
            r = tratativa.tratar_um(sess, cfg, g, clientes, store,
                                    criar_rascunho=True, url_teams=cfg.teams_webhook_url or None)
            return {"status": "ok", "modo": "completo", **r}

        if modo == "real":
            candidatos = [g for g in tratativa.selecionar_candidatos(grupos, clientes)
                          if not store.ja_tratado(g.destinatarios[0].chave)]
            print(f"\n===== TRATAR (REAL — DÁ CIÊNCIA): {len(candidatos)} candidato(s) =====")
            tratados, falhas = 0, 0
            for g in candidatos:
                try:
                    tratativa.tratar_um(sess, cfg, g, clientes, store,
                                        criar_rascunho=True, url_teams=cfg.teams_webhook_url or None)
                    tratados += 1
                except Exception as e:
                    falhas += 1
                    print(f"  erro ao tratar {g.processo}: {e}")
            return {"status": "ok" if falhas == 0 else "parcial", "modo": "real",
                    "candidatos": len(candidatos), "tratados": tratados, "falhas": falhas}

    return {"status": "erro", "erro": f"modo inválido: {modo}"}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="seibot.monitor", description="Monitor de Intimações SEI")
    parser.add_argument("comando", choices=["run", "baseline", "dry-run", "tratar"])
    parser.add_argument("--modo", choices=["ensaio", "completo", "real"], default="ensaio",
                        help="modo do 'tratar' (default: ensaio)")
    parser.add_argument("--processo", default=None,
                        help="nº do processo (para 'tratar --modo completo')")
    args = parser.parse_args(argv)

    cfg = load_config()
    if args.comando == "run":
        res = _cmd_run(cfg)
    elif args.comando == "baseline":
        res = _cmd_baseline(cfg)
    elif args.comando == "tratar":
        res = _cmd_tratar(cfg, args.modo, args.processo)
    else:
        res = _cmd_dry_run(cfg)

    print(json.dumps(res, ensure_ascii=False), flush=True)
    return 0 if res.get("status") in ("ok", "parcial") else 1


if __name__ == "__main__":
    raise SystemExit(main())
