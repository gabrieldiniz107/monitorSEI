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
import traceback
from datetime import date, datetime
from typing import Callable

from . import (classificar, clientes as clientes_mod, datas, erros, intimacoes,
               notify, oficio_card)
from .config import Config, load_config
from .models import Grupo
from .store import IntimacoesStore


def _data_key(d: str):
    try:
        return datetime.strptime(d, "%d/%m/%Y").date()
    except Exception:
        return date.min


def _registrar_promessas(store: IntimacoesStore, g: Grupo, clientes, log) -> int:
    """Registra a promessa de tratativa feita ao grupo do Jurídico.

    A condição é EXATAMENTE a de `notify._decisao_individual` ao imprimir "▶️ Cliente
    ATIVO e adimplente — seguir com a tratativa individual": individual + o cliente passa
    em `motivo_sem_tratativa`. Fonte única para as duas nunca divergirem — mesmo princípio
    já usado entre `notify` e `tratativa`.

    Sem isto, uma promessa que deixa de ser candidata até o `tratar` das 07:10 some sem
    rastro (incidente da Age Telecomunicações, 05/08/2026).
    """
    if clientes is None or g.tipo != "individual":
        return 0
    intim = g.destinatarios[0]
    if clientes_mod.motivo_sem_tratativa(clientes.info(intim.documento)) is not None:
        return 0
    store.registrar_promessa(intim, g.oficio_desc)
    log(f"  ↳ promessa de tratativa registrada: {g.processo} | {intim.destinatario}")
    return 1


def executar(
    cfg: Config,
    *,
    page,
    store: IntimacoesStore,
    enviar: Callable[[Grupo], None],
    clientes=None,
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
    notificados = falhas = prometidos = 0
    for g in novos:
        try:
            enviar(g)
        except Exception as e:  # não marca → retry no próximo ciclo
            falhas += 1
            log(f"  erro ao notificar ofício {g.doc_id}: {e}")
            erros.notificar_erro(cfg, f"run · notificar ofício {g.doc_id}", e, log=log,
                                 detalhe=f"<b>Processo:</b> {g.processo}<br>"
                                         "Não marcado como visto; retenta no próximo ciclo.")
            continue
        for i in g.destinatarios:
            store.marcar_visto(i, g.tipo)
        # só depois do envio bem-sucedido: a promessa só existe se o Jurídico a recebeu
        prometidos += _registrar_promessas(store, g, clientes, log)
        notificados += 1

    return {"status": "ok" if falhas == 0 else "parcial",
            "coletados": len(intims), "grupos": len(grupos),
            "novos": len(novos), "notificados": notificados,
            "prometidos": prometidos, "falhas": falhas}


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
                        clientes=clientes, paginas=cfg.run_paginas)


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


def _reconciliar_promessas(cfg: Config, store: IntimacoesStore, grupos: list[Grupo],
                           clientes, concluidas: set, log=print) -> int:
    """Fecha o ciclo: toda promessa aberta ou foi cumprida, ou rende um aviso com o motivo.

    Este é o conserto do incidente de 05/08/2026: a promessa some da seleção e ninguém
    sabe. Agora, se a intimação ainda está na raspagem mas não é mais candidata, o motivo
    exato vai para o grupo do Jurídico; se sumiu da janela de 100 linhas, avisa uma vez.
    """
    from . import tratativa
    from .store import PROMESSA_DESCARTADA, PROMESSA_TRATADA
    from .teams import enviar_teams_webhook

    # indexa por destinatário: a promessa é de UMA empresa, mas o ofício pode ter virado
    # coletivo desde o `run` — e é justamente esse caso que precisa ser explicado.
    por_chave = {i.chave: g for g in grupos for i in g.destinatarios}

    avisos = 0
    for p in store.promessas_abertas():
        chave = p["chave"]
        if chave in concluidas:
            store.quitar_promessa(chave, PROMESSA_TRATADA)
            continue

        g = por_chave.get(chave)
        if g is None:
            # saiu da janela de 100 linhas raspadas — pode voltar num ciclo futuro.
            # Avisa uma vez e mantém aberta.
            if p.get("avisada"):
                continue
            motivo = ("a intimação saiu da janela de raspagem (100 mais recentes) "
                      "antes de ser tratada")
            store.marcar_promessa_avisada(chave)
        else:
            motivo = tratativa.motivo_nao_candidato(g, clientes, promessa_aberta=True)
            if motivo is None:
                continue  # ainda é candidata: foi falha de tratativa, já alertada por DM
            store.quitar_promessa(chave, PROMESSA_DESCARTADA, motivo, avisada=True)

        log(f"  ⚠️ promessa não cumprida: {p['processo']} | {p['empresa']} — {motivo}")
        if cfg.teams_webhook_url:
            try:
                enviar_teams_webhook(
                    cfg.teams_webhook_url,
                    notify.formatar_promessa_nao_cumprida(p, motivo),
                    cfg.teams_webhook_style)
                avisos += 1
            except Exception as e:  # noqa: BLE001 — avisar não pode derrubar o comando
                log(f"     (falhou ao avisar o grupo: {e})")
                erros.notificar_erro(cfg, f"aviso de promessa não cumprida · {p['processo']}",
                                     e, log=log)
    return avisos


def _cmd_prazos(cfg: Config, hoje: date | None = None) -> dict:
    """Fase 3 — acompanhamento de prazos (roda 1x/dia; NÃO acessa o SEI).

    Para cada tratativa com prazo e contagem ativa: consulta a raia do card no Kanban
    **antes** de qualquer aviso (exigência do usuário) e então
      - raia == 'Aguardando documentação (cliente)' → avisa se hoje é dia da cadência;
      - saiu da raia                                → avisa que a contagem PAROU e para;
      - sem card                                    → avisa o Jurídico e para (sem raia
        não dá para acompanhar).
    """
    hoje = hoje or date.today()
    if not cfg.teams_webhook_url:
        return {"status": "erro", "erro": "TEAMS_WEBHOOK_INTIMACOES_URL não configurado."}

    store = IntimacoesStore(cfg.seen_db_path)
    clientes = clientes_mod.carregar_clientes()
    g = getattr(clientes, "graph", None)
    if g is None:
        return {"status": "erro",
                "erro": "SharePoint indisponível — sem o Kanban não dá para saber a raia."}

    from .teams import enviar_teams_webhook as _envia
    return acompanhar_prazos(
        store=store, cards=_indexar_cards(g), hoje=hoje,
        enviar=lambda msg: _envia(cfg.teams_webhook_url, msg, cfg.teams_webhook_style))


def acompanhar_prazos(*, store: IntimacoesStore, cards: dict, hoje: date,
                      enviar, log=print) -> dict:
    """Núcleo do acompanhamento, com dependências injetadas (mesmo padrão do `executar`).

    ⚠️ Consulta a raia do Kanban **antes** de qualquer aviso — exigência do usuário: se o
    card saiu de 'Aguardando documentação (cliente)', a mensagem que sai é a de PARADA da
    contagem, nunca mais um lembrete de prazo.
    """
    from . import prazos

    linhas = store.em_acompanhamento()
    avisos = paradas = sem_card = 0
    for linha in linhas:
        card = cards.get((linha["processo"], linha["doc_id"])) or cards.get((linha["processo"], ""))
        if card is None:
            log(f"  ⚠️ sem card: {linha['processo']} | doc {linha['doc_id']}")
            enviar(prazos.formatar_sem_card(linha))
            store.parar_acompanhamento(linha["chave"], prazos.PARADA_SEM_CARD)
            sem_card += 1
            continue

        status = (card.get("StatusOficio") or "").strip()
        if status != oficio_card.STATUS_AGUARDANDO:
            log(f"  ⏹️ parou: {linha['processo']} — Kanban agora '{status or '(branco)'}'")
            enviar(prazos.formatar_parada(linha, prazos.PARADA_SAIU_DA_RAIA, status))
            store.parar_acompanhamento(linha["chave"], prazos.PARADA_SAIU_DA_RAIA)
            paradas += 1
            continue

        d = prazos.decidir(linha["data_limite"], linha["prazo_dias"], hoje,
                           ja_avisou_hoje=(linha.get("acomp_ultimo_aviso") == hoje.isoformat()))
        if d is None or not d.avisar:
            continue
        log(f"  ⏳ aviso: {linha['processo']} — faltam {d.faltam} dia(s)")
        enviar(prazos.formatar_aviso(linha, d))
        store.marcar_aviso_prazo(linha["chave"], hoje.isoformat())
        avisos += 1

    return {"status": "ok", "acompanhando": len(linhas), "avisos": avisos,
            "paradas": paradas, "sem_card": sem_card}


def _indexar_cards(g) -> dict:
    """(processo, doc_id) -> fields do card, mais (processo, '') como alternativa.

    O `doc_id` sai do `NumeroOficio` ("Ofício 407 (15843941)"). A entrada com doc_id
    vazio cobre card criado à mão, sem o nº do documento no campo.
    ⚠️ Processo com mais de uma intimação tem UM card só (a criação é idempotente por nº
    do processo) — as duas linhas caem no mesmo card e param juntas.
    """
    import re
    cards = {}
    for it in g.itens(oficio_card.LISTA_CONTROLE_OFICIO, top=200):
        f = it.get("fields", {})
        titulo = (f.get("Title") or "").strip()
        m = re.search(r"\((\d{5,})\)", f.get("NumeroOficio") or "")
        cards[(titulo, m.group(1) if m else "")] = f
        cards.setdefault((titulo, ""), f)
    return cards


def _cmd_tratar(cfg: Config, modo: str = "ensaio", processo_alvo: str | None = None,
                doc_id_alvo: str | None = None) -> dict:
    """Fase 2 — tratativa individual, em 3 modos:
    - ensaio (default): só LISTA candidatos (individual+ativo+Pendente). NÃO abre nada.
    - completo <--processo P>: ENSAIO GERAL num processo JÁ CUMPRIDO (Situação != Pendente):
      roda todo o pipeline e CRIA um rascunho de verdade, SEM dar ciência nova. Valida tudo.
    - real: trata os PENDENTES de verdade → **DÁ CIÊNCIA** (inicia prazo). Cria rascunho.
    """
    from . import sessao, tratativa

    # trava deliberada, verificada ANTES do login (não gasta 2FA para descobrir que está
    # desarmada): dar ciência sozinho exige TRATAR_AUTO=true. Falha ALTO, nunca silencioso.
    if modo == "real" and not cfg.tratar_auto:
        return {"status": "erro", "modo": "real",
                "erro": "TRATAR_AUTO=false no .env — o modo real dá CIÊNCIA (inicia prazo "
                        "legal) e está desarmado. Ligue TRATAR_AUTO=true para armar."}
    # Ciência só em dia útil (decisão do usuário, 2026-08-05): iniciar prazo legal em
    # sábado/domingo é decisão do Jurídico, não da automação. Verificado ANTES do login,
    # como a trava do TRATAR_AUTO — não gasta 2FA. As candidatas continuam Pendentes e
    # são pegas na segunda; a promessa segue aberta, sem falso alarme na reconciliação.
    if modo == "real" and not datas.eh_dia_util(date.today()):
        return {"status": "ok", "modo": "real", "candidatos": 0, "tratados": 0,
                "pulado": "fim de semana — ciência só em dia útil"}
    if modo == "completo" and not (processo_alvo or doc_id_alvo):
        return {"status": "erro", "erro": "modo completo exige --processo <nº> ou --doc-id <id>."}

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
            # --doc-id desambigua processo com MAIS DE UMA intimação: casar só por
            # `processo` pega o primeiro grupo e abre a intimação errada (visto na Maxxnet
            # 53524.000048/2026-12, com 2 Notificações de Lançamento).
            alvo = f"doc {doc_id_alvo}" if doc_id_alvo else processo_alvo
            g = next((x for x in grupos if x.tipo == "individual"
                      and (x.doc_id == doc_id_alvo if doc_id_alvo else x.processo == processo_alvo)),
                     None)
            if g is None:
                return {"status": "erro", "erro": f"intimação individual ({alvo}) não achada na página."}
            if g.situacao == "Pendente":
                return {"status": "erro",
                        "erro": "ABORTADO: processo Pendente — o ensaio-completo só roda em já cumprido (não dar ciência)."}
            print(f"\n===== TRATAR (ENSAIO-COMPLETO) em {g.processo} / {g.oficio_desc} "
                  f"({g.doc_id}) (Situação: {g.situacao}) =====")
            r = tratativa.tratar_um(sess, cfg, g, clientes, store, criar_rascunho=True,
                                    dar_ciencia=False,  # ensaio NUNCA dá ciência
                                    url_teams=cfg.teams_webhook_url or None)
            return {"status": "ok", "modo": "completo", **r}

        if modo == "real":
            # promessas abertas: além de serem reconciliadas no fim, elas AUTORIZAM tratar
            # uma intimação cuja ciência já foi dada por um humano (ver motivo_nao_candidato).
            prometidas = {p["chave"] for p in store.promessas_abertas()}
            candidatos = [g for g in tratativa.selecionar_candidatos(grupos, clientes, prometidas)
                          if not store.ja_tratado(g.destinatarios[0].chave)]
            print(f"\n===== TRATAR (REAL — DÁ CIÊNCIA): {len(candidatos)} candidato(s) "
                  f"| {len(prometidas)} promessa(s) aberta(s) =====")
            tratados, falhas, criticas = 0, 0, 0
            concluidas: set = set()
            for g in candidatos:
                try:
                    tratativa.tratar_um(sess, cfg, g, clientes, store, criar_rascunho=True,
                                        dar_ciencia=True,  # modo real: DÁ CIÊNCIA
                                        url_teams=cfg.teams_webhook_url or None)
                    tratados += 1
                    concluidas.add(g.destinatarios[0].chave)
                except tratativa.TratativaIncompleta as e:
                    # ciência JÁ dada: prazo correndo, sem retry automático, cliente não avisado
                    criticas += 1
                    falhas += 1
                    print(f"  ERRO CRÍTICO em {g.processo}: {e}")
                    erros.notificar_erro(
                        cfg, f"tratar --modo real · {g.processo}", e, critico=True,
                        detalhe=(f"<b>Empresa:</b> {e.empresa}<br>"
                                 f"<b>Ofício:</b> {g.oficio_desc} ({g.doc_id})<br>"
                                 "⚠️ <b>A CIÊNCIA JÁ FOI DADA — o prazo está correndo.</b><br>"
                                 "O bot não vai tentar de novo (checkpoint no store) e o cliente "
                                 "<b>não recebeu</b> o rascunho. Tratar à mão."))
                except Exception as e:  # noqa: BLE001 — qualquer falha, mapeada ou não
                    falhas += 1
                    print(f"  erro ao tratar {g.processo}: {e}")
                    erros.notificar_erro(
                        cfg, f"tratar --modo real · {g.processo}", e,
                        detalhe=(f"<b>Empresa:</b> {g.destinatarios[0].destinatario}<br>"
                                 f"<b>Ofício:</b> {g.oficio_desc} ({g.doc_id})<br>"
                                 "Ciência NÃO foi dada; será retentado no próximo ciclo."))
            # fecha o ciclo: nenhuma promessa pode terminar a execução sem destino
            avisos = _reconciliar_promessas(cfg, store, grupos, clientes, concluidas)
            return {"status": "ok" if falhas == 0 else "parcial", "modo": "real",
                    "candidatos": len(candidatos), "tratados": tratados,
                    "falhas": falhas, "criticas": criticas,
                    "promessas_abertas": len(prometidas), "avisos_promessa": avisos}

    return {"status": "erro", "erro": f"modo inválido: {modo}"}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="seibot.monitor", description="Monitor de Intimações SEI")
    parser.add_argument("comando",
                        choices=["run", "baseline", "dry-run", "tratar", "prazos"])
    parser.add_argument("--modo", choices=["ensaio", "completo", "real"], default="ensaio",
                        help="modo do 'tratar' (default: ensaio)")
    parser.add_argument("--processo", default=None,
                        help="nº do processo (para 'tratar --modo completo')")
    parser.add_argument("--doc-id", dest="doc_id", default=None,
                        help="id do documento no SEI — desambigua processo com mais de "
                             "uma intimação (para 'tratar --modo completo')")
    args = parser.parse_args(argv)

    # o load_config pode falhar (.env incompleto) antes de existir cfg p/ notificar
    try:
        cfg = load_config()
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"status": "erro", "erro": f"config: {e}"}, ensure_ascii=False))
        return 1

    # Rede de segurança: QUALQUER exceção não tratada, em qualquer passo, vira alerta no
    # Teams do responsável técnico. Sem isso uma falha no cron morre silenciosa no log.
    try:
        if args.comando == "run":
            res = _cmd_run(cfg)
        elif args.comando == "baseline":
            res = _cmd_baseline(cfg)
        elif args.comando == "tratar":
            res = _cmd_tratar(cfg, args.modo, args.processo, args.doc_id)
        elif args.comando == "prazos":
            res = _cmd_prazos(cfg)
        else:
            res = _cmd_dry_run(cfg)
    except Exception as e:  # noqa: BLE001 — inclusive erros não mapeados
        ctx = f"monitor {args.comando}"
        if args.comando == "tratar":
            ctx += f" --modo {args.modo}"
        erros.notificar_erro(cfg, ctx, e)
        print(json.dumps({"status": "erro", "comando": args.comando,
                          "erro": f"{type(e).__name__}: {e}"}, ensure_ascii=False), flush=True)
        traceback.print_exc()
        return 1

    print(json.dumps(res, ensure_ascii=False), flush=True)
    if res.get("status") == "erro":
        erros.notificar_erro(cfg, f"monitor {args.comando}",
                             RuntimeError(res.get("erro", "falha sem detalhe")))
    return 0 if res.get("status") in ("ok", "parcial") else 1


if __name__ == "__main__":
    raise SystemExit(main())
