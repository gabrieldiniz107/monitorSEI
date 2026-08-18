"""Raspagem da tela 'Intimações Eletrônicas' do SEI Acesso Externo.

Separação proposital: `parse_pagina(html)` é PURA (string → list[Intimacao]),
testável com fixtures sem navegador. As funções de navegação usam a Playwright
`Page` de uma `LoginSession` já autenticada.

⚠️ Só lê a listagem. NUNCA aciona a coluna "Ações"/lupa nem abre a intimação
(isso daria ciência e iniciaria o prazo).
"""
from __future__ import annotations

import html as _html
import re
from typing import Iterator

from .models import Intimacao, normalizar_cnpj

# link do menu para a tela (a href carrega o infra_hash fresco da sessão)
LINK_INTIMACOES = "a[href*='md_pet_intimacao_usu_ext_listar']"
TABELA_SELECTOR = "table[summary^='Intima']"

_TABELA_RE = re.compile(r'<table[^>]*summary="Intima[^"]*".*?</table>', re.S | re.I)
_ROW_RE = re.compile(r'<tr[^>]*data-idintimacao=.*?</tr>', re.S)
_DOC_RE = re.compile(r'^(.*?)\s*\((\d+)\)\s*$')
_DOCNUM_RE = re.compile(r'(\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}|\d{3}\.\d{3}\.\d{3}-\d{2})')
_TOTAL_RE = re.compile(r'Lista de Intima\w+ Eletr\w+\s*\((\d+)\s+registros\s*-\s*(\d+)\s+a\s+(\d+)\)', re.I)


# ----------------------------------------------------------------------------
# Parser puro
# ----------------------------------------------------------------------------
def _strip(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", _html.unescape(s)).strip()


def _celula(row: str, label: str) -> str:
    m = re.search(rf'<td[^>]*data-label="{re.escape(label)}"[^>]*>(.*?)</td>', row, re.S)
    return _strip(m.group(1)) if m else ""


def _attr(row: str, name: str) -> str:
    m = re.search(rf'{re.escape(name)}="([^"]*)"', row)
    return m.group(1).strip() if m else ""


def _parse_documento_principal(texto: str, row: str) -> tuple[str, str]:
    """'Ofício 498 (15963368)' -> ('Ofício 498', '15963368').
    Fallback nos atributos data-doctipo / data-docprinc da linha."""
    m = _DOC_RE.match(texto)
    if m:
        return m.group(1).strip(), m.group(2)
    return _attr(row, "data-doctipo") or texto, _attr(row, "data-docprinc")


def _parse_destinatario(texto: str) -> tuple[str, str, str]:
    """'Razão Social (CNPJ)' -> (nome, doc_normalizado, doc_formatado)."""
    m = _DOCNUM_RE.search(texto)
    doc_fmt = m.group(1) if m else ""
    nome = re.sub(r"\s*\([\d./\-]+\)\s*$", "", texto).strip() if m else texto.strip()
    return nome, normalizar_cnpj(doc_fmt), doc_fmt


_CONSULTA_RE = re.compile(r"window\.open\('([^']*processo_acesso_externo_consulta[^']*)'\)")


def _parse_consulta_url(row: str) -> str:
    m = _CONSULTA_RE.search(row)
    if not m:
        return ""
    url = _html.unescape(m.group(1))
    return url if url.startswith("http") else "https://sei.anatel.gov.br/sei/" + url


def _parse_linha(row: str) -> Intimacao:
    processo = _celula(row, "Processo")
    oficio_desc, doc_id = _parse_documento_principal(_celula(row, "Documento Principal"), row)
    nome, doc, doc_fmt = _parse_destinatario(_celula(row, "Destinatário"))
    return Intimacao(
        processo=processo,
        doc_id=doc_id,
        oficio_desc=oficio_desc,
        destinatario=nome,
        documento=doc,
        documento_fmt=doc_fmt,
        tipo_destinatario=_celula(row, "Tipo de Destinatário"),
        tipo_intimacao=_celula(row, "Tipo de Intimação"),
        data_expedicao=_celula(row, "Data de Expedição"),
        situacao=_celula(row, "Situação"),
        id_acesso_externo=_attr(row, "data-idacext"),
        consulta_url=_parse_consulta_url(row),
    )


def parse_pagina(html: str) -> list[Intimacao]:
    """Extrai as intimações de uma página da listagem. Função pura."""
    mt = _TABELA_RE.search(html)
    if not mt:
        return []
    return [_parse_linha(r) for r in _ROW_RE.findall(mt.group(0))]


def ler_total(html: str) -> int | None:
    """Total de registros informado no cabeçalho da lista, se presente."""
    m = _TOTAL_RE.search(html)
    return int(m.group(1)) if m else None


# ----------------------------------------------------------------------------
# Navegação (Playwright)
# ----------------------------------------------------------------------------
def _ir_para_intimacoes(page, *, log=print) -> None:
    href = page.locator(LINK_INTIMACOES).first.get_attribute("href")
    log(f"→ Intimações: {href}")
    page.set_default_navigation_timeout(60000)
    try:
        page.goto(href, wait_until="commit")
    except Exception as e:  # SEI mantém conexões abertas; 'commit' às vezes estoura
        log(f"  (aviso goto: {e})")
    _esperar_tabela(page)


def _esperar_tabela(page, timeout: int = 30000) -> None:
    """Espera a listagem estar pronta para ser lida.

    Ordem importa: primeiro o **load state**, senão `page.content()` estoura com
    "Unable to retrieve content because the page is navigating" — foi o que derrubava a
    paginação e o filtro (achado em 18/08/2026, ao tentar alcançar uma intimação antiga).
    Depois a tabela, e só então o settle: a tabela (~200KB) pode ainda estar renderizando
    após o 'commit', e ler cedo demais corta linhas.
    """
    for estado in ("domcontentloaded", "load"):
        try:
            page.wait_for_load_state(estado, timeout=timeout)
        except Exception:
            pass
    page.wait_for_selector(TABELA_SELECTOR, timeout=timeout)
    try:
        page.wait_for_selector("#lnkInfraProximaPaginaInferior, #divInfraAreaTabela", timeout=10000)
    except Exception:
        pass
    page.wait_for_timeout(2500)


def ler_html(page, tentativas: int = 3) -> str:
    """`page.content()` à prova de navegação em curso (o postback do SEI é assíncrono)."""
    ultimo = None
    for _ in range(tentativas):
        try:
            return page.content()
        except Exception as e:  # noqa: BLE001 — "page is navigating": esperar e reler
            ultimo = e
            try:
                page.wait_for_load_state("load", timeout=15000)
            except Exception:
                page.wait_for_timeout(1500)
    raise RuntimeError(f"não foi possível ler a página após {tentativas} tentativas: {ultimo}")


def _avancar_pagina(page, *, log=print) -> bool:
    """Vai para a próxima página via a função JS do SEI. True se avançou."""
    if page.locator("#lnkInfraProximaPaginaSuperior").count() == 0:
        return False
    try:
        antes = page.locator("#hdnInfraPaginaAtual").get_attribute("value")
    except Exception:
        antes = None
    # o link é onclick JS (javascript:void) → chamar a função global, não clicar.
    # O postback navega: esperar a navegação TERMINAR antes de ler qualquer coisa.
    try:
        with page.expect_navigation(wait_until="domcontentloaded", timeout=30000):
            try:
                page.evaluate("infraAcaoPaginar('+',0,'Infra', null)")
            except Exception:
                pass  # o postback destrói o contexto do evaluate — esperado
    except Exception:
        pass      # sem navegação detectada: ainda assim conferimos a tabela abaixo
    try:
        _esperar_tabela(page)
    except Exception as e:
        log(f"  (aviso paginação: {e})")
        return False
    try:
        depois = page.locator("#hdnInfraPaginaAtual").get_attribute("value")
        if antes is not None and depois == antes:
            return False  # não avançou
    except Exception:
        pass
    return True


def _iter_paginas(page, *, paginas: int, log=print) -> Iterator[str]:
    """Itera o HTML das primeiras `paginas` páginas (topo = mais recentes).

    A lista vem ordenada do mais novo p/ o mais antigo, então raspar o topo basta
    para detectar novidades. Não toca na coluna 'Ações'.
    """
    for n in range(1, paginas + 1):
        html = ler_html(page)
        yield html
        m = _TOTAL_RE.search(html)
        if m:  # já cobrimos tudo?
            total, _, ate = (int(x) for x in m.groups())
            if ate >= total:
                return
        if n >= paginas:
            return
        if not _avancar_pagina(page, log=log):
            return


def coletar(page, cfg, *, paginas: int = 1, log=print) -> list[Intimacao]:
    """Navega até Intimações e raspa as `paginas` primeiras (mais recentes)."""
    _ir_para_intimacoes(page, log=log)
    vistos: set[str] = set()
    out: list[Intimacao] = []
    for html in _iter_paginas(page, paginas=paginas, log=log):
        for intim in parse_pagina(html):
            if intim.chave not in vistos:
                vistos.add(intim.chave)
                out.append(intim)
    log(f"→ Coletadas {len(out)} intimações (até {paginas} página(s)).")
    return out
