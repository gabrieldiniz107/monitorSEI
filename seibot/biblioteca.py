"""Publicação dos documentos do ofício na biblioteca compartilhada com os clientes.

Site **CLIENTES E PARCEIROS** → biblioteca **DOCUMENTOS** → pasta **Ofícios Jurídicos
Anatel**, onde o Jurídico já mantém à mão uma pasta por ofício (47 quando isto foi escrito)
e que é **compartilhada com os clientes**. É o canal pelo qual a empresa recebe o ofício —
por isso o fluxo coletivo não manda e-mail: publicar aqui já entrega.

Usa o **mesmo app app-only do `graph.py`** ("SCM VISTORIAS", `Sites.ReadWrite.All`), que já
alcança este site — validado ao vivo em 2026-08-05. Nenhuma credencial nova.

⚠️ Só entram aqui documentos **da intimação** (ofício + anexos apontados pelos ícones de
aceite). A Lista de Protocolos traz o processo inteiro, incluindo documentos internos da
Anatel — mandá-los ao cliente seria vazamento (ver o incidente da SPEEDMAX no CLAUDE.md).
"""
from __future__ import annotations

import re
from typing import Optional

from .models import Grupo

# ids descobertos via Graph em 2026-08-05 (site CLIENTESEPARCEIROS, biblioteca DOCUMENTOS)
SITE_CLIENTES_PARCEIROS = ("scmprovedor.sharepoint.com,26994668-c8ea-478f-97ad-dd7d0e2ea10f,"
                           "0c7dc03a-e980-4020-8258-c35aff99de34")
DRIVE_DOCUMENTOS = "b!aEaZJurIj0eXrd19Di6hDzrAfQyA6SBAgljDWv-Z3jTI0XcQGMw8SotDVyYY154f"
PASTA_RAIZ = "Ofícios Jurídicos Anatel"

PDF_MIME = "application/pdf"

_INVALIDOS = re.compile(r'[\\/:*?"<>|#%\x00-\x1f]')


def _limpo(texto: str) -> str:
    """Nome utilizável no SharePoint (que proíbe \\ / : * ? " < > | # %)."""
    return re.sub(r"\s{2,}", " ", _INVALIDOS.sub("-", texto or "")).strip(" .")


def nome_pasta(grupo: Grupo) -> str:
    """`Ofício 600 (15955558)` — nº do ofício + id do documento no SEI.

    O número sozinho se repete entre anos e unidades (as pastas manuais já misturam
    "Ofício 600", "Ofício nº 600" e "Oficio 721"); o id do SEI é único e amarra a pasta à
    intimação que a originou.
    """
    return _limpo(f"{grupo.oficio_desc} ({grupo.doc_id})")


def nome_oficio(grupo: Grupo) -> str:
    """`Ofício 600 (15955558).pdf` — mesmo nome da pasta, como nas pastas manuais."""
    return f"{nome_pasta(grupo)}.pdf"


def nome_anexo(ordem: int, num: str, tipo: str) -> str:
    """`[1]-15944017_Planilha.pdf` — a convenção do ZIP do SEI, que é a usada à mão."""
    return _limpo(f"[{ordem}]-{num}_{tipo or 'Anexo'}") + ".pdf"


def caminho_pasta(grupo: Grupo) -> str:
    return f"{PASTA_RAIZ}/{nome_pasta(grupo)}"


def publicar(g, grupo: Grupo, oficio_pdf: bytes,
             anexos: Optional[list] = None, log=print) -> str:
    """Cria/reusa a pasta do ofício, sobe ofício + anexos e devolve o **link da pasta**.

    `anexos` = [(nome_do_arquivo, bytes)] — já nomeados por `nome_anexo`.
    Idempotente: repetir sobrescreve os mesmos arquivos (ver `graph.upload_arquivo`).
    """
    pasta = g.garantir_pasta(DRIVE_DOCUMENTOS, PASTA_RAIZ, nome_pasta(grupo))
    base = caminho_pasta(grupo)

    g.upload_arquivo(DRIVE_DOCUMENTOS, f"{base}/{nome_oficio(grupo)}", oficio_pdf, PDF_MIME)
    for nome, conteudo in (anexos or []):
        g.upload_arquivo(DRIVE_DOCUMENTOS, f"{base}/{nome}", conteudo, PDF_MIME)

    log(f"   ✓ publicado em '{base}' ({1 + len(anexos or [])} arquivo(s))")
    return pasta.get("webUrl", "")
