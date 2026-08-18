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
from dataclasses import dataclass
from typing import Optional

from .models import Grupo

# ids descobertos via Graph em 2026-08-05 (site CLIENTESEPARCEIROS, biblioteca DOCUMENTOS)
SITE_CLIENTES_PARCEIROS = ("scmprovedor.sharepoint.com,26994668-c8ea-478f-97ad-dd7d0e2ea10f,"
                           "0c7dc03a-e980-4020-8258-c35aff99de34")
DRIVE_DOCUMENTOS = "b!aEaZJurIj0eXrd19Di6hDzrAfQyA6SBAgljDWv-Z3jTI0XcQGMw8SotDVyYY154f"
PASTA_RAIZ = "Ofícios Jurídicos Anatel"

PDF_MIME = "application/pdf"

# --- Fase 5: minutas de dilação (INTERNO) --------------------------------------------
# ⚠️ Destino deliberadamente DIFERENTE do de cima. A biblioteca acima é compartilhada com
# os clientes; uma minuta é peça em elaboração, que só o Jurídico pode ver antes de revisar.
# Site **Gestão Integrada** (o interno, o mesmo do Kanban e da base de clientes), biblioteca
# "Documentos" — id descoberto via Graph em 2026-08-18.
DRIVE_GESTAO_INTEGRADA = "b!dTqThO0N40ieHelWa4PGzapZYkGQ8u5GlRs0NpuFwbsprt2-ZrAiQZhUoshN9Z9F"
PASTA_MINUTAS = "Jurídico/Minutas de Dilação de Prazo"

DOCX_MIME = ("application/vnd.openxmlformats-officedocument."
             "wordprocessingml.document")

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


def nome_pasta_minuta(oficio_desc: str, doc_id: str) -> str:
    return _limpo(f"{oficio_desc} ({doc_id})")


def caminho_minuta(oficio_desc: str, doc_id: str, arquivo: str) -> str:
    return f"{PASTA_MINUTAS}/{nome_pasta_minuta(oficio_desc, doc_id)}/{_limpo(arquivo)}"


@dataclass(frozen=True)
class PublicacaoMinuta:
    arquivo_url: str
    pasta_url: str
    extras: int = 0          # ofício + anexos que acompanharam a minuta


def publicar_minuta(g, oficio_desc: str, doc_id: str, arquivo: str, docx: bytes,
                    extras: Optional[list] = None, log=print) -> PublicacaoMinuta:
    """Sobe a minuta na biblioteca **interna**, com o ofício e os anexos junto.

    A pasta é o dossiê do caso (pedido do usuário, 18/08/2026): quem revisa a minuta precisa
    conferir contra o ofício e os anexos, e ir buscá-los no SEI a cada revisão é o trabalho
    que esta fase existe para evitar. `extras` = `[(nome, bytes)]`, vindos de
    `dossie.carregar` — os mesmos arquivos que foram para o rascunho de e-mail.

    Os dois links voltam porque ambos vão para o Teams: o **arquivo** abre direto no Word, a
    **pasta** mostra o conjunto.

    ⚠️ A minuta sobe **primeiro**, e cada extra é best-effort: um anexo grande demais (o
    upload simples do Graph para em ~4 MB) ou um erro de rede não podem custar a peça, que é
    o que o Jurídico precisa ter em mãos antes do vencimento.

    Idempotente (`conflictBehavior=replace`): regerar substitui em vez de criar "(1)".
    """
    caminho = caminho_minuta(oficio_desc, doc_id, arquivo)
    base = caminho.rsplit("/", 1)[0]
    pasta = g.garantir_caminho(DRIVE_GESTAO_INTEGRADA, base)
    item = g.upload_arquivo(DRIVE_GESTAO_INTEGRADA, caminho, docx, DOCX_MIME)
    log(f"   ✓ minuta publicada em '{caminho}'")

    subidos = 0
    for nome, conteudo in (extras or []):
        try:
            g.upload_arquivo(DRIVE_GESTAO_INTEGRADA, f"{base}/{_limpo(nome)}", conteudo,
                             PDF_MIME)
            subidos += 1
        except Exception as e:  # noqa: BLE001 — a minuta já está publicada; ver docstring
            log(f"   ⚠️ anexo '{nome}' não subiu ({e}) — a minuta está publicada")
    if subidos:
        log(f"   ✓ + {subidos} arquivo(s) do ofício na mesma pasta")
    return PublicacaoMinuta((item or {}).get("webUrl", ""), (pasta or {}).get("webUrl", ""),
                            subidos)
