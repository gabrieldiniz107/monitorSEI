"""Registro do que já foi notificado (dedup) e do ciclo de vida da tratativa. SQLite (stdlib).

Espelha o SeenStore do scm-watchers: conexão efêmera por operação, INSERT OR IGNORE.
A chave é `intimacao.chave` = processo|doc_id|cnpj.

Três tabelas:
- `intimacoes` — o que já foi notificado no Teams (dedup da Fase 1).
- `tratadas`   — checkpoint da Fase 2. Gravado logo após a CIÊNCIA para impedir retry
  automático (ciência é irreversível), e completado no fim com o prazo capturado.
- `promessas`  — o que o `run` prometeu tratar, para o `tratar` reconciliar depois.
  Sem isto, uma intimação prometida que deixa de ser candidata some sem deixar rastro.
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from typing import Iterable, Optional

from .models import Intimacao

# estados de uma promessa
PROMESSA_ABERTA = "aberta"
PROMESSA_TRATADA = "tratada"
PROMESSA_DESCARTADA = "descartada"
PROMESSA_FALHOU = "falhou"


class IntimacoesStore:
    def __init__(self, path: str):
        self._path = path
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        with closing(sqlite3.connect(self._path)) as con:
            con.execute(
                "CREATE TABLE IF NOT EXISTS intimacoes ("
                " chave TEXT PRIMARY KEY,"
                " processo TEXT,"
                " doc_id TEXT,"
                " cnpj TEXT,"
                " situacao TEXT,"
                " grupo_tipo TEXT,"
                " data_expedicao TEXT,"
                " visto_em TEXT DEFAULT CURRENT_TIMESTAMP)"
            )
            # Fase 2: intimações já TRATADAS (rascunho criado) — para não repetir.
            con.execute(
                "CREATE TABLE IF NOT EXISTS tratadas ("
                " chave TEXT PRIMARY KEY,"
                " processo TEXT,"
                " doc_id TEXT,"
                " cnpj TEXT,"
                " data_limite TEXT,"
                " tratado_em TEXT DEFAULT CURRENT_TIMESTAMP)"
            )
            # Promessas de tratativa feitas pelo `run` (ver docstring do módulo).
            con.execute(
                "CREATE TABLE IF NOT EXISTS promessas ("
                " chave TEXT PRIMARY KEY,"
                " processo TEXT,"
                " doc_id TEXT,"
                " cnpj TEXT,"
                " empresa TEXT,"
                " oficio_desc TEXT,"
                " situacao_na_promessa TEXT,"
                " estado TEXT DEFAULT 'aberta',"
                " motivo TEXT DEFAULT '',"
                " avisada INTEGER DEFAULT 0,"
                " prometida_em TEXT DEFAULT CURRENT_TIMESTAMP,"
                " atualizado_em TEXT DEFAULT CURRENT_TIMESTAMP)"
            )
            # migração in-place: bancos já em produção não têm as colunas de prazo
            self._garantir_colunas(con, "tratadas",
                                   {"prazo_dias": "INTEGER", "prazo_unidade": "TEXT"})
            con.commit()

    @staticmethod
    def _garantir_colunas(con, tabela: str, colunas: dict) -> None:
        """ADD COLUMN para colunas ausentes (SQLite não tem IF NOT EXISTS aqui).

        O banco de produção já existe com o schema antigo e é montado por volume — não
        dá para recriá-lo. `PRAGMA table_info` diz o que já está lá.
        """
        existentes = {r[1] for r in con.execute(f"PRAGMA table_info({tabela})")}
        for nome, tipo in colunas.items():
            if nome not in existentes:
                con.execute(f"ALTER TABLE {tabela} ADD COLUMN {nome} {tipo}")

    def ja_visto(self, chave: str) -> bool:
        with closing(sqlite3.connect(self._path)) as con:
            return con.execute(
                "SELECT 1 FROM intimacoes WHERE chave = ?", (chave,)
            ).fetchone() is not None

    def marcar_visto(self, intim: Intimacao, grupo_tipo: str = "") -> None:
        with closing(sqlite3.connect(self._path)) as con:
            con.execute(
                "INSERT OR IGNORE INTO intimacoes "
                "(chave, processo, doc_id, cnpj, situacao, grupo_tipo, data_expedicao) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (intim.chave, intim.processo, intim.doc_id, intim.documento,
                 intim.situacao, grupo_tipo, intim.data_expedicao),
            )
            con.commit()

    def marcar_lote(self, intims: Iterable[Intimacao], grupo_tipo: str = "baseline") -> int:
        """Marca várias intimações como vistas sem notificar (usado pelo comando baseline)."""
        linhas = [
            (i.chave, i.processo, i.doc_id, i.documento, i.situacao, grupo_tipo, i.data_expedicao)
            for i in intims
        ]
        with closing(sqlite3.connect(self._path)) as con:
            con.executemany(
                "INSERT OR IGNORE INTO intimacoes "
                "(chave, processo, doc_id, cnpj, situacao, grupo_tipo, data_expedicao) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                linhas,
            )
            con.commit()
        return len(linhas)

    def contar(self) -> int:
        with closing(sqlite3.connect(self._path)) as con:
            return con.execute("SELECT COUNT(*) FROM intimacoes").fetchone()[0]

    # --- Fase 2: tratadas ---
    def ja_tratado(self, chave: str) -> bool:
        with closing(sqlite3.connect(self._path)) as con:
            return con.execute(
                "SELECT 1 FROM tratadas WHERE chave = ?", (chave,)
            ).fetchone() is not None

    def marcar_tratado(self, intim: Intimacao, data_limite: str = "",
                       prazo_dias: Optional[int] = None, prazo_unidade: str = "") -> None:
        """Marca a intimação como tratada e grava o prazo.

        ⚠️ Chamado DUAS vezes no `--modo real`: uma como checkpoint logo após a ciência
        (sem prazo — o prazo só é legível depois), e outra no fim, com o prazo capturado.
        Era `INSERT OR IGNORE`, então a segunda gravação era descartada e o prazo se
        perdia: as 12 linhas do banco de produção estavam todas com `data_limite` vazio,
        inclusive as cujo log mostrava a data certa (bug achado em 05/08/2026).

        O UPDATE é condicional a `excluded.data_limite != ''` de propósito: se o pipeline
        for retomado e o checkpoint (sem prazo) rodar depois, ele **não** pode apagar um
        prazo já gravado.
        """
        with closing(sqlite3.connect(self._path)) as con:
            con.execute(
                "INSERT INTO tratadas "
                "(chave, processo, doc_id, cnpj, data_limite, prazo_dias, prazo_unidade) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(chave) DO UPDATE SET "
                " data_limite = excluded.data_limite,"
                " prazo_dias = excluded.prazo_dias,"
                " prazo_unidade = excluded.prazo_unidade "
                "WHERE excluded.data_limite != ''",
                (intim.chave, intim.processo, intim.doc_id, intim.documento,
                 data_limite, prazo_dias, prazo_unidade),
            )
            con.commit()

    def prazo_de(self, chave: str) -> Optional[tuple]:
        """(data_limite, prazo_dias, prazo_unidade) do que já foi tratado, ou None."""
        with closing(sqlite3.connect(self._path)) as con:
            return con.execute(
                "SELECT data_limite, prazo_dias, prazo_unidade FROM tratadas WHERE chave = ?",
                (chave,),
            ).fetchone()

    # --- Fase 2: promessas de tratativa (reconciliação run → tratar) ---
    def registrar_promessa(self, intim: Intimacao, oficio_desc: str = "") -> None:
        """O `run` prometeu tratar esta intimação. Re-registrar não reabre uma já quitada."""
        with closing(sqlite3.connect(self._path)) as con:
            con.execute(
                "INSERT OR IGNORE INTO promessas "
                "(chave, processo, doc_id, cnpj, empresa, oficio_desc, situacao_na_promessa) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (intim.chave, intim.processo, intim.doc_id, intim.documento,
                 intim.destinatario, oficio_desc, intim.situacao),
            )
            con.commit()

    def promessas_abertas(self) -> list[dict]:
        with closing(sqlite3.connect(self._path)) as con:
            con.row_factory = sqlite3.Row
            return [dict(r) for r in con.execute(
                "SELECT * FROM promessas WHERE estado = ? ORDER BY prometida_em",
                (PROMESSA_ABERTA,))]

    def quitar_promessa(self, chave: str, estado: str, motivo: str = "",
                        avisada: bool = False) -> None:
        with closing(sqlite3.connect(self._path)) as con:
            con.execute(
                "UPDATE promessas SET estado = ?, motivo = ?, avisada = ?,"
                " atualizado_em = CURRENT_TIMESTAMP WHERE chave = ?",
                (estado, motivo, 1 if avisada else 0, chave),
            )
            con.commit()

    def marcar_promessa_avisada(self, chave: str) -> None:
        """Promessa que continua aberta mas já rendeu aviso — não repetir a cada ciclo."""
        with closing(sqlite3.connect(self._path)) as con:
            con.execute(
                "UPDATE promessas SET avisada = 1, atualizado_em = CURRENT_TIMESTAMP"
                " WHERE chave = ?", (chave,))
            con.commit()
