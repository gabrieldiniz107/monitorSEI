"""Backfill pontual: recupera os prazos perdidos na tabela `tratadas`.

Contexto (05/08/2026). `store.marcar_tratado` usava `INSERT OR IGNORE`, e o `--modo real`
grava DUAS vezes: o checkpoint logo após a ciência (sem prazo, porque o prazo só é legível
depois) e a gravação final com o prazo capturado. A segunda era descartada — as 12 linhas
do banco de produção ficaram com `data_limite` vazio, mesmo com o log da execução mostrando
a data certa (ex. FONELIGHT, `prazo: 03/09/2026`).

O código já foi corrigido (UPSERT), mas as linhas antigas não se autocorrigem. A fonte de
recuperação são os **cards do Kanban**: `oficio_card.montar_campos` grava `DataVencimento`
a partir do mesmo objeto `Prazo`, e essa gravação nunca teve o bug.

Casa por (nº do processo, doc_id): `Title` do card = nº do processo e `NumeroOficio` =
"Ofício N (docid)" — o doc_id entre parênteses é o que desambigua processo com mais de uma
intimação (caso Maxxnet, 2 Notificações de Lançamento no mesmo processo).

Uso (na VPS, dentro do container, para enxergar o volume `state/`):
    docker compose run --rm sei-monitor python backfill_prazos.py --dry-run
    docker compose run --rm sei-monitor python backfill_prazos.py --aplicar
"""
from __future__ import annotations

import argparse
import re
import sqlite3
from contextlib import closing

from seibot import graph, oficio_card
from seibot.config import load_config

_DOC_ID_RE = re.compile(r"\((\d{5,})\)")


def _doc_id_do_card(numero_oficio: str) -> str:
    """'Ofício 407 (15843941)' -> '15843941'."""
    m = _DOC_ID_RE.search(numero_oficio or "")
    return m.group(1) if m else ""


def _ddmmaaaa(iso: str) -> str:
    """'2026-09-03T03:00:00Z' -> '03/09/2026'. '' se não parsear (inclusive o
    30/12/1899 que as colunas de data em branco exibem)."""
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", iso or "")
    if not m:
        return ""
    aaaa, mm, dd = m.groups()
    return "" if aaaa == "1899" else f"{dd}/{mm}/{aaaa}"


def prazos_dos_cards(g) -> dict:
    """(processo, doc_id) -> data_limite 'dd/mm/aaaa', a partir do Kanban do Jurídico."""
    out = {}
    for it in g.itens(oficio_card.LISTA_CONTROLE_OFICIO, top=200):
        f = it.get("fields", {})
        venc = _ddmmaaaa(f.get("DataVencimento") or "")
        if not venc:
            continue
        out[((f.get("Title") or "").strip(), _doc_id_do_card(f.get("NumeroOficio") or ""))] = venc
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Backfill de data_limite em `tratadas`")
    ap.add_argument("--aplicar", action="store_true",
                    help="grava de verdade (sem isto, só mostra o que faria)")
    args = ap.parse_args()

    cfg = load_config()
    por_card = prazos_dos_cards(graph.cliente())
    print(f"→ {len(por_card)} card(s) com DataVencimento no Kanban.")

    with closing(sqlite3.connect(cfg.seen_db_path)) as con:
        vazias = con.execute(
            "SELECT chave, processo, doc_id FROM tratadas "
            "WHERE data_limite IS NULL OR data_limite = ''").fetchall()
        print(f"→ {len(vazias)} linha(s) de `tratadas` sem prazo.\n")

        achados = 0
        for chave, processo, doc_id in vazias:
            venc = por_card.get((processo, doc_id))
            if not venc:
                print(f"  ✗ {processo} | doc {doc_id} — sem card correspondente (tratar à mão)")
                continue
            achados += 1
            print(f"  ✓ {processo} | doc {doc_id} -> {venc}")
            if args.aplicar:
                con.execute("UPDATE tratadas SET data_limite = ? WHERE chave = ?",
                            (venc, chave))
        if args.aplicar:
            con.commit()

    print(f"\n{achados}/{len(vazias)} recuperável(is)."
          + ("" if args.aplicar else "  (ensaio — rode com --aplicar para gravar)"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
