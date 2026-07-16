"""Fase 2 / Increment 3 — abrir o processo, capturar o prazo e baixar ofício + anexos.

Mecânica validada ao vivo (2026-07-16):
- Ofício: `documento_consulta_externa.php?...&id_documento=X` → HTML (ISO-8859-1).
- Anexos: referenciados NO TEXTO do ofício como "(SEI nº NNNNNN)"; casam com o nº visível
  na Lista de Protocolos do processo, de onde se baixa o PDF (ctx.request.get().body()).
  Ofício sem "(SEI nº …)" ⇒ sem anexos.
- Prazo: na linha do ofício, o ícone `intimacao_peticionar_resposta` leva (via window.location)
  à página `acao=md_pet_responder_intimacao_usu_ext`, cujo `#selTipoResposta` tem a opção
  "<Tipo> (<N> Dias) - Data Limite: DD/MM/AAAA".

⚠️ A página de resposta é um formulário de peticionamento — aqui SÓ LEMOS o prazo; nunca
preenchemos nem enviamos.
"""
from __future__ import annotations

import html as _html
import re
from dataclasses import dataclass
from typing import Optional

BASE = "https://sei.anatel.gov.br/sei/"

_ANEXO_RE = re.compile(r"\(\s*SEI\s*n[^\d]{0,6}(\d{5,})", re.I)
_PRAZO_RE = re.compile(
    r"(?P<tipo>.+?)\(\s*(?P<dias>\d+)\s*Dias?\s*\)\s*-\s*Data\s*Limite:\s*(?P<data>\d{2}/\d{2}/\d{4})",
    re.I,
)


# ----------------------------------------------------------------------------
# Parsers puros (testáveis sem browser)
# ----------------------------------------------------------------------------
def _para_texto(oficio_html: str) -> str:
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", oficio_html)))


def extrair_anexos(oficio_html: str) -> list[str]:
    """Números SEI dos anexos citados no texto do ofício (ordem preservada, sem repetir)."""
    return list(dict.fromkeys(_ANEXO_RE.findall(_para_texto(oficio_html))))


@dataclass(frozen=True)
class Prazo:
    tipo: str          # ex. "Defesa Preliminar"
    dias: int          # ex. 15
    data_limite: str   # ex. "30/07/2026"


def parse_prazo(opcao: str) -> Optional[Prazo]:
    """Extrai o prazo do texto de uma opção do #selTipoResposta.
    Ex.: 'Defesa Preliminar (15 Dias) - Data Limite: 30/07/2026'."""
    m = _PRAZO_RE.search(opcao or "")
    if not m:
        return None
    return Prazo(tipo=m.group("tipo").strip(" -– "),
                dias=int(m.group("dias")), data_limite=m.group("data"))


# ----------------------------------------------------------------------------
# Navegação / download (Playwright — sobre uma sessão logada)
# ----------------------------------------------------------------------------
def _abs(url: str) -> str:
    url = _html.unescape(url)
    return url if url.startswith("http") else BASE + url


def abrir_processo(page, consulta_url: str) -> None:
    """Abre a página do processo (Disponibilização Parcial de Documentos) e carrega os
    ícones lazy rolando a página inteira."""
    try:
        page.goto(_abs(consulta_url), wait_until="commit")
    except Exception:
        pass
    page.wait_for_timeout(3000)
    page.evaluate(
        "async ()=>{for(let y=0;y<=document.body.scrollHeight;y+=300){window.scrollTo(0,y);"
        "await new Promise(r=>setTimeout(r,120));}}"
    )
    page.wait_for_timeout(2500)


def mapa_protocolos(page) -> dict:
    """nº visível do documento -> {url, tipo} (Lista de Protocolos do processo)."""
    itens = page.evaluate(
        "()=>[...document.querySelectorAll('a')]"
        ".filter(a=>(a.getAttribute('href')||'').includes('documento_consulta_externa.php'))"
        ".map(a=>{const tr=a.closest('tr');const tds=tr?tr.querySelectorAll('td'):[];"
        "const t=[...tds].find(td=>td.getAttribute('data-label')==='Tipo');"
        "return {num:a.textContent.trim(), href:a.getAttribute('href'), tipo:t?t.textContent.trim():''};})"
    )
    return {i["num"]: {"url": _abs(i["href"]), "tipo": re.sub(r"\s+", " ", i["tipo"]).strip()}
            for i in itens}


def baixar(context, url: str) -> bytes:
    """Baixa o conteúdo bruto de um documento (PDF de anexo, ou HTML do ofício)."""
    r = context.request.get(_abs(url))
    if r.status >= 400:
        raise RuntimeError(f"download {url} -> HTTP {r.status}")
    return r.body()


def oficio_pdf(page, oficio_url: str) -> bytes:
    """Renderiza a página do ofício (HTML) e devolve como PDF (Chromium headless).
    ⚠️ page.pdf() só funciona em headless."""
    try:
        page.goto(_abs(oficio_url), wait_until="commit")
    except Exception:
        pass
    page.wait_for_timeout(2000)
    return page.pdf(format="A4", print_background=True)


def url_peticionar_resposta(page) -> Optional[str]:
    """URL da página de resposta (onde está o prazo), a partir do ícone azul da linha do
    ofício. None se a intimação não exige resposta (ex.: mero Conhecimento)."""
    oc = page.evaluate(
        "()=>{const a=[...document.querySelectorAll('a')].find(x=>"
        "(x.querySelector('img')?.getAttribute('src')||'').includes('intimacao_peticionar_resposta'));"
        "return a?a.getAttribute('onclick'):'';}"
    )
    m = re.search(r"window\.location\s*=\s*'([^']+)'", oc or "") or \
        re.search(r"window\.open\('([^']+)'", oc or "")
    return _abs(m.group(1)) if m else None


def capturar_prazo(page, resposta_url: str) -> Optional[Prazo]:
    """Abre a página de resposta (SÓ LEITURA) e lê o prazo do #selTipoResposta.
    ⚠️ NÃO preenche nem envia nada."""
    try:
        page.goto(_abs(resposta_url), wait_until="commit")
    except Exception:
        pass
    page.wait_for_timeout(2500)
    opcoes = page.evaluate(
        "()=>{const s=document.querySelector('#selTipoResposta');"
        "return s?[...s.options].map(o=>o.textContent.trim()):[];}"
    )
    for op in opcoes:
        p = parse_prazo(op)
        if p:
            return p
    return None
