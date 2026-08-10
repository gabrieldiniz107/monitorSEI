"""Backfill pontual: cria o card dos ofícios COLETIVOS tratados ANTES de 10/08/2026.

Contexto. Até 07/08 o coletivo não tinha card no Kanban e, por isso, `coletivo._apos_ciencia`
gravava o prazo e **desligava** o acompanhamento na hora (`parar_acompanhamento` com
"coletivo — sem card no Kanban, prazo acompanhado pelo Jurídico"). Em 10/08 o coletivo passou
a ter card e a ser acompanhado como o individual — mas as linhas já paradas **não se
reativam sozinhas**: `marcar_tratado` não mexe em `acomp_estado`.

Sem este backfill, os coletivos de 07/08 (todos com prazo 14/08) seguiriam sem acompanhamento
justamente na semana do vencimento.

O que faz, por ofício (agrupando as N linhas por processo + doc_id):
1. cria o card no Kanban (idempotente por nº do processo, como o fluxo normal);
2. posta o comentário de proveniência com as empresas e o link da pasta;
3. reativa as linhas de `tratadas` (`acomp_estado='ativo'`, `grupo_tipo='coletivo'`).

⚠️ **Prioridade sai como "Média".** O bot a deriva do "URGENTE" no Tipo de Intimação, e esse
campo não é guardado em `tratadas` — reconstruí-lo exigiria voltar ao SEI (outro 2FA). Na
execução de 10/08/2026 os 7 ofícios eram todos URGENTE (5 dias, vencendo 14/08), então os
cards 46–52 foram corrigidos para "Alta" por PATCH depois. O acompanhamento de prazo não
depende desse campo.

**Não acessa o SEI.** Só SQLite + SharePoint.

Uso (na VPS, dentro do container, para enxergar o volume `state/`):
    docker compose run --rm sei-monitor python backfill_cards_coletivo.py
    docker compose run --rm sei-monitor python backfill_cards_coletivo.py --aplicar
"""
from __future__ import annotations

import argparse
import sqlite3
from contextlib import closing
from datetime import date

from seibot import biblioteca, comentarios, graph, oficio_card
from seibot.config import load_config
from seibot.models import Grupo, Intimacao
from seibot.processo import Prazo
from seibot.store import IntimacoesStore

# o motivo gravado pela versão antiga do `coletivo._apos_ciencia`
MOTIVO_ANTIGO = "coletivo%"


def _linhas_paradas(con) -> list:
    con.row_factory = sqlite3.Row
    return [dict(r) for r in con.execute(
        "SELECT * FROM tratadas WHERE acomp_estado = 'parado' AND acomp_motivo LIKE ?"
        " AND data_limite IS NOT NULL AND data_limite != '' ORDER BY doc_id",
        (MOTIVO_ANTIGO,))]


def _agrupar(linhas: list) -> dict:
    """(processo, doc_id) -> lista de linhas do mesmo ofício."""
    grupos: dict = {}
    for linha in linhas:
        grupos.setdefault((linha["processo"], linha["doc_id"]), []).append(linha)
    return grupos


def _grupo_de(linhas: list) -> Grupo:
    """Reconstrói o `Grupo` a partir das linhas — só o que o card e o comentário usam.

    `tipo_intimacao` fica vazio de propósito: não é guardado em `tratadas` (ver docstring).
    """
    p, d = linhas[0]["processo"], linhas[0]["doc_id"]
    oficio = linhas[0].get("oficio_desc") or "Ofício"
    destinatarios = tuple(
        Intimacao(processo=p, doc_id=d, oficio_desc=oficio,
                  destinatario=linha.get("empresa") or "(empresa não registrada)",
                  documento=linha.get("cnpj") or "", documento_fmt=linha.get("cnpj") or "",
                  tipo_destinatario="Pessoa Jurídica", tipo_intimacao="",
                  data_expedicao="", situacao="")
        for linha in linhas)
    return Grupo(processo=p, doc_id=d, oficio_desc=oficio, tipo_intimacao="",
                 data_expedicao="", situacao="", destinatarios=destinatarios)


def _prazo_de(linha: dict) -> Prazo:
    return Prazo(tipo="", dias=linha.get("prazo_dias") or 0,
                 data_limite=linha["data_limite"],
                 unidade=linha.get("prazo_unidade") or "dias")


def _pasta_de(g, grupo: Grupo) -> str:
    """webUrl da pasta já publicada, se ela existir (o link vai no lembrete de prazo)."""
    try:
        item = g.item_do_drive(biblioteca.DRIVE_DOCUMENTOS, biblioteca.caminho_pasta(grupo))
        return (item or {}).get("webUrl", "")
    except Exception as e:  # noqa: BLE001 — o link é conforto, não requisito
        print(f"     ⚠️ não achei a pasta: {e}")
        return ""


def main() -> int:
    ap = argparse.ArgumentParser(description="Cria os cards dos coletivos já tratados")
    ap.add_argument("--aplicar", action="store_true",
                    help="grava de verdade (sem isto, só mostra o que faria)")
    ap.add_argument("--doc-id", dest="doc_id", default=None,
                    help="limita a ofícios específicos (vários separados por vírgula)")
    args = ap.parse_args()
    alvos = [d.strip() for d in (args.doc_id or "").split(",") if d.strip()]

    cfg = load_config()
    g = graph.cliente()
    # abre o store uma vez só para disparar a migração (`grupo_tipo`/`pasta_url`): o resto
    # do script fala SQL cru, e num banco não-migrado o UPDATE quebraria no meio do laço —
    # com cards já criados e linhas não reativadas.
    IntimacoesStore(cfg.seen_db_path)

    with closing(sqlite3.connect(cfg.seen_db_path)) as con:
        grupos = _agrupar(_linhas_paradas(con))
        if alvos:
            grupos = {k: v for k, v in grupos.items() if k[1] in alvos}
        print(f"→ {len(grupos)} ofício(s) coletivo(s) parado(s) com prazo.\n")

        criados = reativados = 0
        for (processo, doc_id), linhas in grupos.items():
            grupo = _grupo_de(linhas)
            prazo = _prazo_de(linhas[0])
            print(f"  • {processo} | {grupo.oficio_desc} ({doc_id}) | "
                  f"{len(linhas)} empresa(s) | vence {prazo.data_limite}")
            if not args.aplicar:
                continue

            pasta = _pasta_de(g, grupo)
            cid = oficio_card.criar_card_coletivo(
                g, grupo, prazo, data_cumprimento=date.today(),
                log=lambda m: print(f"    {m.strip()}"))
            if cid:
                criados += 1
                try:
                    comentarios.postar_comentario(
                        cfg, oficio_card.LISTA_CONTROLE_OFICIO, cid,
                        comentarios.texto_card_coletivo(grupo, pasta))
                    print("     ✓ comentário de automação postado")
                except Exception as e:  # noqa: BLE001 — cosmético
                    print(f"     ⚠️ comentário falhou: {e}")

            for linha in linhas:
                con.execute(
                    "UPDATE tratadas SET acomp_estado='ativo', acomp_motivo='',"
                    " grupo_tipo='coletivo', pasta_url=COALESCE(NULLIF(?,''), pasta_url)"
                    " WHERE chave = ?", (pasta, linha["chave"]))
                reativados += 1
            con.commit()

    print(f"\n{criados} card(s) criado(s), {reativados} linha(s) reativada(s)."
          + ("" if args.aplicar else "  (ensaio — rode com --aplicar para gravar)"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
