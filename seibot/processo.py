"""Fase 2 — abrir o processo, DAR CIÊNCIA, capturar o prazo e baixar ofício + anexos.

Mecânica validada ao vivo numa intimação PENDENTE real (2026-07-20, proc 53508.003179/2026-50):

- **Abrir o processo NÃO dá ciência.** `processo_acesso_externo_consulta.php` só mostra o
  cabeçalho, a Lista de Protocolos (números/tipos) e os Andamentos. Antes da ciência os
  links dos documentos são inertes (`onclick="…alert('Sem acesso ao documento.')"`), o
  `mapa_protocolos` volta VAZIO e o ícone de resposta (prazo) NÃO existe.
- **A ciência é um passo discreto**: na linha de cada documento há um ícone
  `intimacao_nao_cumprida_doc_principal|doc_anexo.svg` cujo onclick é
  `infraAbrirJanelaModal('…acao=md_pet_intimacao_usu_ext_confirmar_aceite&…')`. Essa tela
  explica o aceite e traz o botão **`#sbmAceitarIntimacao`** ("Confirmar Consulta à
  Intimação"). Confirmar UM documento cumpre a intimação inteira (mesmo `id_intimacao[]`).
- **Depois da ciência** os links viram `documento_consulta_externa.php?...&id_documento=X`,
  nasce a "Certidão de Intimação Cumprida" na lista e aparece o ícone de resposta.
- Ofício: `documento_consulta_externa.php` → HTML (ISO-8859-1).
- **Anexos: vêm da Lista de Protocolos**, não do texto do ofício. São os documentos que não
  são o ofício nem a Certidão de Intimação Cumprida. (O texto do ofício às vezes cita
  "(SEI nº NNNNNN)", mas nem sempre cita todos — no Ofício 70 citava 1 de 2.)
- Prazo: o ícone `intimacao_peticionar_resposta` leva (via window.location) à página
  `acao=md_pet_responder_intimacao_usu_ext`, cujo `#selTipoResposta` tem a opção
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
# A unidade pode vir com qualificador: "(15 Dias)", "(20 Dias Úteis)", "(30 Dias Corridos)".
# `unidade` captura "Dias"/"Dias Úteis"/etc. — dia útil ≠ dia corrido importa juridicamente,
# então preservamos o rótulo em vez de assumir "dias". (Bug 2026-07-22: a Cobrança de Crédito
# Tributário da Maxxnet usava "20 Dias Úteis" e o regex antigo, preso em "Dias)", devolvia None
# → o bot dizia "sem prazo de resposta" mesmo com Data Limite legível no #selTipoResposta.)
_PRAZO_RE = re.compile(
    r"(?P<tipo>.+?)\(\s*(?P<dias>\d+)\s*(?P<unidade>Dias?(?:\s+[^\s)]+)?)\s*\)"
    r"\s*-\s*Data\s*Limite:\s*(?P<data>\d{2}/\d{2}/\d{4})",
    re.I,
)


# ----------------------------------------------------------------------------
# Parsers puros (testáveis sem browser)
# ----------------------------------------------------------------------------
def _para_texto(oficio_html: str) -> str:
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", oficio_html)))


def extrair_anexos(oficio_html: str) -> list[str]:
    """Números SEI dos anexos citados no texto do ofício (ordem preservada, sem repetir).

    ⚠️ Fonte SECUNDÁRIA: nem todo ofício cita todos os anexos. A primária são os documentos
    da intimação (ícones de aceite) — ver `anexos_da_intimacao()`."""
    return list(dict.fromkeys(_ANEXO_RE.findall(_para_texto(oficio_html))))


# documentos da Lista de Protocolos que NÃO são anexos a enviar ao cliente
_NAO_ANEXO_RE = re.compile(r"certid[ãa]o\s+de\s+intima[çc][ãa]o", re.I)


def anexos_da_intimacao(protocolos: dict, doc_id_oficio: str,
                        docs_intimacao: "list[str] | None" = None,
                        citados: "list[str] | None" = None) -> list[str]:
    """Números dos anexos a enviar ao cliente: os documentos **da intimação**, menos o ofício.

    `docs_intimacao` são os nºs lidos dos ícones de aceite ANTES da ciência — é a definição
    do próprio SEI de "documentos desta intimação" (doc principal + doc anexo). Fonte
    PRIMÁRIA, porque a Lista de Protocolos traz o processo INTEIRO, com documentos internos
    da Anatel que não fazem parte da intimação e não devem ir para o cliente. Validado em
    21/07/2026 no proc 53539.000753/2026-51: a intimação tinha 2 documentos (Ofício 268 +
    Despacho Decisório 476) e a lista tinha 4 — sobravam "Consulta CNPJ" e "Consulta".

    Sem `docs_intimacao` (processo já cumprido: os ícones de aceite somem após a ciência),
    cai para os "(SEI nº …)" citados no texto do ofício. `citados` também define a ordem.
    """
    base = list(docs_intimacao) if docs_intimacao else list(citados or [])
    nums = [n for n in dict.fromkeys(base)
            if n != doc_id_oficio and n in protocolos
            and not _NAO_ANEXO_RE.search(protocolos[n].get("tipo", ""))]
    if not citados:
        return nums
    ordem = {n: i for i, n in enumerate(citados)}
    return sorted(nums, key=lambda n: (ordem.get(n, len(ordem)), n))


@dataclass(frozen=True)
class Prazo:
    tipo: str            # ex. "Defesa Preliminar"
    dias: int            # ex. 15
    data_limite: str     # ex. "30/07/2026"
    unidade: str = "dias"  # ex. "dias" / "dias úteis" — dia útil ≠ dia corrido


def parse_prazo(opcao: str) -> Optional[Prazo]:
    """Extrai o prazo do texto de uma opção do #selTipoResposta.
    Ex.: 'Defesa Preliminar (15 Dias) - Data Limite: 30/07/2026'
      ou 'Impugnação (20 Dias Úteis) - Data Limite: 19/08/2026'."""
    m = _PRAZO_RE.search(opcao or "")
    if not m:
        return None
    unidade = re.sub(r"\s+", " ", m.group("unidade")).strip().lower() or "dias"
    return Prazo(unidade=unidade, tipo=m.group("tipo").strip(" -– "),
                dias=int(m.group("dias")), data_limite=m.group("data"))


# ----------------------------------------------------------------------------
# Navegação / download (Playwright — sobre uma sessão logada)
# ----------------------------------------------------------------------------
def _abs(url: str) -> str:
    url = _html.unescape(url)
    return url if url.startswith("http") else BASE + url


# mensagens de erro do Playwright que significam "a página navegou embaixo de nós".
# São transitórias: basta reabrir. NÃO inclui "browser has been closed" (aí retentar é inútil).
_ERROS_NAVEGACAO = (
    "execution context was destroyed",
    "frame was detached",
    "frame got detached",
    "navigating and changing the content",
)

# teto de passos do scroll (300px cada) — trava contra página que cresce sem parar
_MAX_PASSOS_SCROLL = 60


def _eh_erro_navegacao(exc: Exception) -> bool:
    return any(m in str(exc).lower() for m in _ERROS_NAVEGACAO)


def _scroll_lazy(page) -> None:
    """Rola a página até o fim, em passos CURTOS, para disparar o lazy-load dos ícones de Ação.

    Antes isto era UM `evaluate` assíncrono longo (o laço de scroll rodava inteiro dentro do
    browser, vários segundos). Se a página navegasse sozinha nesse meio-tempo, o contexto JS
    morria e o Playwright levantava "Execution context was destroyed" — foi o que derrubou a
    tratativa do proc 53539.000753/2026-51 em 21/07/2026. Em passos curtos, cada `evaluate`
    dura milissegundos: a janela de exposição fica mínima e o que sobrar é retentável.
    """
    altura = page.evaluate("()=>document.body.scrollHeight") or 0
    y = 0
    for _ in range(_MAX_PASSOS_SCROLL):
        if y > altura:
            break
        page.evaluate("y=>window.scrollTo(0,y)", y)
        page.wait_for_timeout(120)
        y += 300
        # o lazy-load faz a página crescer enquanto rolamos
        altura = max(altura, page.evaluate("()=>document.body.scrollHeight") or 0)


def abrir_processo(page, consulta_url: str, tentativas: int = 3) -> None:
    """Abre a página do processo (Disponibilização Parcial de Documentos) e carrega os
    ícones lazy rolando a página inteira.

    Retenta quando a página navega sozinha no meio do carregamento (redirect/recarga do SEI).
    **Retentar aqui é seguro**: abrir o processo NÃO dá ciência — só o clique explícito em
    `#sbmAceitarIntimacao` dá (ver o cabeçalho deste módulo).
    """
    url = _abs(consulta_url)
    for tentativa in range(1, tentativas + 1):
        try:
            try:
                page.goto(url, wait_until="commit")
            except Exception:
                pass  # com 'commit' o goto às vezes levanta mesmo tendo carregado
            try:
                page.wait_for_load_state("domcontentloaded", timeout=15000)
            except Exception:
                pass  # sem DOMContentLoaded seguimos assim mesmo: o settle-wait abaixo cobre
            page.wait_for_timeout(1500)
            _scroll_lazy(page)
            page.wait_for_timeout(2500)
            return
        except Exception as e:
            if tentativa >= tentativas or not _eh_erro_navegacao(e):
                raise
            page.wait_for_timeout(2000)  # deixa a navegação que atropelou terminar


BTN_ACEITAR = "#sbmAceitarIntimacao"


def urls_aceite(page) -> list[dict]:
    """Ícones de aceite da intimação (só existem enquanto ela está PENDENTE).

    -> [{'url', 'num', 'principal'}] — `principal` marca o ícone do Documento Principal
    (o ofício). Lista vazia ⇒ a intimação já foi cumprida (ciência já dada).
    """
    return page.evaluate(
        "()=>[...document.querySelectorAll('a')].map(a=>{"
        "const oc=a.getAttribute('onclick')||'';"
        "const m=oc.match(/infraAbrirJanelaModal\\('([^']+)'/);"
        "if(!m||!m[1].includes('confirmar_aceite'))return null;"
        "const tr=a.closest('tr');const tds=tr?[...tr.querySelectorAll('td')]:[];"
        "const num=tds.find(td=>/^\\d{7,}$/.test(td.innerText.trim()));"
        "const img=a.querySelector('img')?.getAttribute('src')||'';"
        "return {url:m[1],num:num?num.innerText.trim():'',"
        "principal:img.includes('doc_principal')};}).filter(Boolean)"
    )


def dar_ciencia(page, aceite_url: str) -> None:
    """⚠️ IRREVERSÍVEL — abre a tela de aceite e confirma, INICIANDO O PRAZO.

    Confirmar um documento cumpre a intimação inteira (o modal carrega `id_intimacao[]`).
    Levanta se o botão de confirmação não estiver na tela (não clica em nada por adivinhação).
    """
    try:
        page.goto(_abs(aceite_url), wait_until="commit")
    except Exception:
        pass
    page.wait_for_timeout(2500)
    btn = page.locator(BTN_ACEITAR)
    if btn.count() == 0:
        raise RuntimeError(
            f"tela de aceite sem o botão {BTN_ACEITAR} — nada foi confirmado ({page.url})")
    btn.first.click(timeout=20000)
    page.wait_for_timeout(3000)


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


_PDF_MAGIC = b"%PDF"


def eh_pdf(bruto: bytes) -> bool:
    """True se os bytes já são um PDF (magic number). Documentos gerados no SEI vêm em HTML;
    documentos externos (upload/print) e algumas Notificações vêm como PDF de verdade."""
    return bruto[:4] == _PDF_MAGIC


def _pdf_para_texto(pdf_bytes: bytes) -> str:
    """Texto de um PDF via pypdf. '' se não der para extrair (nunca levanta)."""
    import io

    import pypdf
    try:
        r = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        return "\n".join((p.extract_text() or "") for p in r.pages).strip()
    except Exception:
        return ""


def extrair_texto_oficio(bruto: bytes, *, pdf_extractor=_pdf_para_texto) -> str:
    """Texto do ofício (para o resumo LLM e para `extrair_anexos`), escolhendo o decodificador
    certo pelo conteúdo.

    - Ofício **gerado no SEI** vem como **HTML** (ISO-8859-1) → decodifica; o resumo tira as tags.
    - Ofício **servido como PDF** (ex.: Notificação de Lançamento — upload/print externo) precisa
      de **pypdf**. Decodificar o binário do PDF como ISO-8859-1 alimentaria o LLM com lixo — foi
      o que aconteceu no rascunho da Maxxnet (proc 53524.000048/2026-12, doc 16003317, 2026-07-22):
      resumo genérico/inventado a partir de bytes de PDF. `pdf_extractor` é injetável (testes).
    """
    if eh_pdf(bruto):
        return pdf_extractor(bruto)
    return bruto.decode("iso-8859-1", errors="replace")


def baixar_como_pdf(page, context, url: str) -> bytes:
    """Baixa um documento da intimação e devolve SEMPRE um PDF abrível.

    ⚠️ Bug corrigido em 2026-07-22 (rascunho da SITELBRA, proc 53500.064050/2024-26): os
    anexos eram baixados crus (`baixar`) e salvos com extensão `.pdf`. Mas documentos
    **gerados no SEI** (Ofício, Despacho Decisório, Informe, Nota Técnica…) NÃO são PDF —
    `documento_consulta_externa.php` os serve como **HTML** (por isso o ofício tem o
    `oficio_pdf` dedicado, e por isso `_tratar_apos_ciencia` decodifica o ofício como
    ISO-8859-1 para o resumo). Salvar esse HTML como `.pdf` gera um arquivo que **não abre**.
    Só documentos **externos** (upload — ex.: Extrato de Lançamentos) já vêm em PDF.

    Detecta pelo magic number: se já é PDF, devolve os bytes crus; senão (HTML gerado no
    SEI) renderiza a página via Chromium (`page.pdf`, só headless), igual ao ofício.
    """
    bruto = baixar(context, url)
    if eh_pdf(bruto):
        return bruto
    return oficio_pdf(page, url)


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
