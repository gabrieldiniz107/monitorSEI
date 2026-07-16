"""Registro do que já foi notificado (dedup). SQLite (stdlib).

Espelha o SeenStore do scm-watchers: conexão efêmera por operação, INSERT OR IGNORE.
A chave é `intimacao.chave` = processo|doc_id|cnpj.
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from typing import Iterable

from .models import Intimacao


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
            con.commit()

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

    def marcar_tratado(self, intim: Intimacao, data_limite: str = "") -> None:
        with closing(sqlite3.connect(self._path)) as con:
            con.execute(
                "INSERT OR IGNORE INTO tratadas "
                "(chave, processo, doc_id, cnpj, data_limite) VALUES (?, ?, ?, ?, ?)",
                (intim.chave, intim.processo, intim.doc_id, intim.documento, data_limite),
            )
            con.commit()
