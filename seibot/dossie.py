"""Fase 5 — guarda em disco o ofício e os anexos, para a pasta da minuta de dilação.

Por que disco, e não "baixar de novo na hora": a minuta é gerada pelo comando `prazos`, que
**não acessa o SEI** — é o que permite rodá-lo 1x/dia sem gastar um código 2FA da caixa do
Rodrigo. Os bytes só existem durante a tratativa (quando o bot já está logado), e até aqui
viviam só em memória: iam para o rascunho de e-mail e eram descartados.

Ficam em `state/dossies/<doc_id>/`, ao lado do banco — `state/` é volume no Docker, então
sobrevive a `docker compose build`/recreate, igual ao `intimacoes.db`.

⚠️ Só ofícios tratados a partir desta mudança têm arquivos guardados. Para os anteriores a
pasta da minuta sai só com o `.docx` — mesma limitação do dossiê de texto.
"""
from __future__ import annotations

import os
import re
from typing import Optional

# nome de arquivo seguro em disco E em caminho de SharePoint
_INVALIDOS = re.compile(r'[\\/:*?"<>|#%\x00-\x1f]')


def _limpo(nome: str) -> str:
    return _INVALIDOS.sub("-", nome or "").strip(" .") or "arquivo"


def base_de(db_path: str) -> str:
    """`state/intimacoes.db` → `state/dossies`. Deriva do banco para não criar mais uma
    variável de ambiente: os dois vivem no mesmo volume."""
    return os.path.join(os.path.dirname(db_path) or ".", "dossies")


def pasta(db_path: str, doc_id: str) -> str:
    return os.path.join(base_de(db_path), re.sub(r"\D", "", str(doc_id)) or "sem_doc_id")


def guardar(db_path: str, doc_id: str, arquivos: list, log=print) -> int:
    """Grava `[(nome, bytes)]`. Devolve quantos foram gravados. **Nunca levanta**.

    É insumo de uma peça futura, gravado depois de a ciência já ter sido dada — não pode
    derrubar uma tratativa concluída.
    """
    destino = pasta(db_path, doc_id)
    gravados = 0
    try:
        os.makedirs(destino, exist_ok=True)
        for nome, conteudo in arquivos or []:
            if not conteudo:
                continue
            with open(os.path.join(destino, _limpo(nome)), "wb") as fh:
                fh.write(conteudo)
            gravados += 1
    except Exception as e:  # noqa: BLE001 — ver docstring
        log(f"   ⚠️ falha ao guardar os arquivos do ofício para a minuta: {e}")
    return gravados


def carregar(db_path: str, doc_id: str, log=print) -> list:
    """`[(nome, bytes)]` do que foi guardado, em ordem alfabética (o ofício vem antes dos
    anexos porque `nome_oficio` começa com "0-"). Lista vazia se não houver nada."""
    destino = pasta(db_path, doc_id)
    if not os.path.isdir(destino):
        return []
    saida = []
    try:
        for nome in sorted(os.listdir(destino)):
            caminho = os.path.join(destino, nome)
            if os.path.isfile(caminho):
                with open(caminho, "rb") as fh:
                    saida.append((nome, fh.read()))
    except Exception as e:  # noqa: BLE001 — sem os anexos a minuta ainda é entregável
        log(f"   ⚠️ falha ao ler os arquivos guardados do ofício: {e}")
    return saida


def nome_oficio(oficio_desc: str, doc_id: str) -> str:
    """Prefixo "0-" para o ofício aparecer no topo da pasta, antes dos anexos."""
    return _limpo(f"0-{oficio_desc} ({doc_id})") + ".pdf"


def nome_anexo(ordem: int, num: str, tipo: str) -> str:
    """Mesma convenção do ZIP do SEI já usada na Fase 4, deslocada para depois do ofício."""
    return _limpo(f"{ordem}-{num}_{tipo or 'Anexo'}") + ".pdf"
