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
- ⚠️ **A coluna "Ações" não vem no HTML**: cada linha traz um placeholder
  `.md-pet-acao-lazy` e um loader que busca os botões por AJAX, **um documento por vez, em
  cadeia**. Em processo grande isso leva dezenas de segundos e o `abrir_processo` lê a
  página antes — daí `urls_aceite` chamar o endpoint em lote (`_aceites_lazy`).
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
import time
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


_JS_ACEITES_DOM = """
()=>[...document.querySelectorAll('a')].map(a=>{
  const oc=a.getAttribute('onclick')||'';
  const m=oc.match(/infraAbrirJanelaModal\\('([^']+)'/);
  if(!m||!m[1].includes('confirmar_aceite'))return null;
  const tr=a.closest('tr');const tds=tr?[...tr.querySelectorAll('td')]:[];
  const num=tds.find(td=>/^\\d{7,}$/.test(td.innerText.trim()));
  const img=a.querySelector('img')?.getAttribute('src')||'';
  return {url:m[1],num:num?num.innerText.trim():'',
          principal:img.includes('doc_principal')};
}).filter(Boolean)
"""

# Resolve a coluna "Ações" chamando o endpoint do módulo de peticionamento em LOTE, em vez
# de esperar o lazy-load nativo (ver `_aceites_lazy`). Devolve o HTML já renderizado de cada
# placeholder, junto do nº do documento lido da própria linha.
_JS_ACEITES_LAZY = """
async ()=>{
  const els=[...document.querySelectorAll('.md-pet-acao-lazy')];
  if(!els.length) return [];
  const m=document.documentElement.innerHTML.match(/var mdPetUrl\\s*=\\s*"([^"]+)"/);
  if(!m) return [];
  const itens=els.map(e=>({id:e.dataset.id,acesso:e.dataset.acesso,
                           procedimento:e.dataset.procedimento,isproc:e.dataset.isproc}));
  // NUNCA levanta: o endpoint responde HTTP 500 quando o lote é grande (medido em
  // 07/08/2026 com 16 itens, ofício 682). Se o lote falhar, o `for` abaixo refaz item a
  // item — que é como o loader nativo do SEI sempre faz. Antes isto era um `r.json()`
  // solto: o 500 virava exceção, o fallback nunca rodava, e o bot concluía "sem ícone de
  // aceite" = "ciência já dada".
  async function buscar(lista){
    try{
      const r=await fetch(m[1],{method:'POST',body:JSON.stringify({itens:lista})});
      if(!r.ok) return {};
      const t=await r.text();
      let d; try{ d=JSON.parse(t); }catch(e){ return {}; }
      return (d && d.erro) ? {} : (d||{});
    }catch(e){ return {}; }
  }
  let dados=await buscar(itens);
  const faltando=itens.filter(i=>!(i.id in dados));
  for(const i of faltando){ Object.assign(dados, await buscar([i])); }
  return els.map(e=>{
    const html=dados[e.dataset.id]?atob(dados[e.dataset.id]):'';
    const tr=e.closest('tr');const tds=tr?[...tr.querySelectorAll('td')]:[];
    const num=tds.find(td=>/^\\d{7,}$/.test(td.innerText.trim()));
    return {html:html,num:num?num.innerText.trim():''};
  }).filter(x=>x.html);
}
"""

_MODAL_ACEITE_RE = re.compile(r"infraAbrirJanelaModal\('([^']*confirmar_aceite[^']*)'")


def _acoes_lazy_html(page) -> list[dict]:
    """HTML bruto de cada célula "Ações" que o lazy-load ainda não renderizou.

    ⚠️ Por que isto existe (achado de 2026-08-07, ofício coletivo 693 / proc
    53500.101985/2026-62): a coluna "Ações" não vem no HTML — cada linha traz um
    `<div class="md-pet-acao-lazy">` e um loader que faz **um POST por documento, em
    cadeia** (`get_acoes_protocolo_lista`). Num processo com ~105 documentos a cadeia leva
    dezenas de segundos, e o `abrir_processo` (que espera ~11s) lia a página antes de os
    ícones existirem ⇒ tanto `urls_aceite` (ícone de aceite) quanto `url_peticionar_resposta`
    (ícone de prazo) voltavam vazios — o segundo caso é silencioso: o coletivo é tratado, mas
    sem prazo capturado ele nunca ganha card (2026-08-20, cards de coletivo pararam de
    aparecer no Kanban depois de 10/08 — processos com muitos destinatários/documentos nunca
    terminam de carregar as Ações a tempo do `document.querySelectorAll('a')` de
    `url_peticionar_resposta`, que só lia o DOM já renderizado). Rolar mais não resolve: o
    custo é de rede, não de viewport.

    Chama o mesmo endpoint **em lote**, uma vez, e devolve o HTML de cada botão — quem
    interpreta (aceite ou resposta) é o chamador. É o mesmo GET/POST de leitura que o
    navegador faria — não confirma nada.
    """
    try:
        itens = page.evaluate(_JS_ACEITES_LAZY) or []
    except Exception:
        return []   # sem as ações do lazy seguimos com o que o DOM já mostrava
    return itens


def _aceites_lazy(page) -> list[dict]:
    """Ícones de aceite que o lazy-load da coluna "Ações" ainda não renderizou."""
    achados = []
    for it in _acoes_lazy_html(page):
        m = _MODAL_ACEITE_RE.search(it.get("html") or "")
        if m:
            achados.append({"url": _html.unescape(m.group(1)), "num": it.get("num", ""),
                            "principal": "doc_principal" in it["html"]})
    return achados


_RESPOSTA_ONCLICK_RE = re.compile(
    r"window\.location\s*=\s*'([^']+)'|window\.open\('([^']+)'")


def _resposta_lazy(page) -> Optional[str]:
    """URL da página de resposta, para quando o ícone ainda não estava no DOM renderizado
    (mesmo mecanismo lazy do `_aceites_lazy` — ver seu docstring)."""
    for it in _acoes_lazy_html(page):
        frag = it.get("html") or ""
        if "intimacao_peticionar_resposta" not in frag:
            continue
        m = _RESPOSTA_ONCLICK_RE.search(frag)
        if m:
            return _html.unescape(m.group(1) or m.group(2))
    return None


def aceites_no_dom(page) -> list[dict]:
    """Só o que já está renderizado no DOM — **não** dispara o endpoint das Ações.

    Leitura barata, para conferir se sobrou ícone depois da ciência. Não serve para decidir
    "há aceite?" (o lazy pode não ter carregado ainda) — para isso use `urls_aceite`.
    """
    return page.evaluate(_JS_ACEITES_DOM) or []


def urls_aceite(page) -> list[dict]:
    """Ícones de aceite da intimação (só existem enquanto ela está PENDENTE).

    -> [{'url', 'num', 'principal'}] — `principal` marca o ícone do Documento Principal
    (o ofício). Lista vazia ⇒ a intimação já foi cumprida (ciência já dada).

    Lê o DOM e, para as linhas cuja coluna "Ações" ainda não carregou, resolve o lazy-load
    pelo endpoint (`_aceites_lazy`). Sem esse complemento, processo grande = falso "já
    cumprida".
    """
    achados = aceites_no_dom(page)
    vistos = {a["url"] for a in achados}
    achados += [a for a in _aceites_lazy(page) if a["url"] not in vistos]
    return achados


def escolher_aceite(aceites: list, doc_id: str = "") -> Optional[dict]:
    """Qual ícone de aceite confirmar. Confirmar qualquer um cumpre a intimação inteira (a
    URL carrega todos os `id_intimacao[]`), mas escolhemos o do próprio ofício para que o
    log diga o que foi confirmado.

    Ordem: o documento cujo nº é o do ofício → o marcado como `principal` → o primeiro.
    ⚠️ O marcador `doc_principal` nem sempre vem: no coletivo 693 (2026-08-07) os 4 ícones
    vieram com `principal=False`, e sem o casamento por `doc_id` a escolha seria arbitrária.
    """
    if not aceites:
        return None
    return (next((a for a in aceites if doc_id and a.get("num") == doc_id), None)
            or next((a for a in aceites if a.get("principal")), None)
            or aceites[0])


class CienciaIncerta(RuntimeError):
    """O clique de confirmação foi disparado, mas não deu para confirmar o desfecho.

    ⚠️ Quem trata isto **tem de assumir que a ciência FOI dada** e gravar o checkpoint. Não
    é hipótese: em 07/08/2026, no coletivo 693, o `click()` estourou esperando a navegação
    ("click action done ... waiting for scheduled navigations to finish") e a ciência tinha
    entrado — as 9 empresas viraram "Cumprida por Consulta Direta". Como o erro subiu como
    falha comum, nada foi gravado nem publicado, e a intimação sairia da seleção em silêncio
    no ciclo seguinte (ela deixa de ter destinatário Pendente).
    """


def dar_ciencia(page, aceite_url: str) -> None:
    """⚠️ IRREVERSÍVEL — abre a tela de aceite e confirma, INICIANDO O PRAZO.

    Confirmar um documento cumpre a intimação inteira (o modal carrega `id_intimacao[]`).
    Levanta `RuntimeError` se o botão não estiver na tela (não clica por adivinhação) e
    `CienciaIncerta` se o clique saiu mas o desfecho ficou em aberto.
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
    try:
        # no_wait_after: o clique dispara uma navegação que não assenta (a tela de aceite é
        # um modal do SEI). Sem isto o click() espera a navegação e estoura DEPOIS de já ter
        # clicado — ver CienciaIncerta.
        btn.first.click(timeout=20000, no_wait_after=True)
    except Exception as e:
        raise CienciaIncerta(f"clique em {BTN_ACEITAR} sem desfecho confirmado: {e}") from e
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


def baixar(context, url: str, tentativas: int = 3) -> bytes:
    """Baixa o conteúdo bruto de um documento (PDF de anexo, ou HTML do ofício).

    Timeout generoso + retry: o `documento_consulta_externa.php` do SEI passa dos 30s
    padrão do Playwright em documento grande (visto em 07/08/2026 no Ofício 693). Baixar é
    idempotente, então retentar é seguro — e falhar aqui, depois da ciência, é caro.
    """
    ultimo = None
    for tentativa in range(1, tentativas + 1):
        try:
            r = context.request.get(_abs(url), timeout=120000)
            if r.status >= 400:
                raise RuntimeError(f"download {url} -> HTTP {r.status}")
            return r.body()
        except Exception as e:
            ultimo = e
            if tentativa < tentativas:
                time.sleep(2 ** tentativa)
    raise RuntimeError(f"download {url} falhou após {tentativas} tentativas: {ultimo}")


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
    ofício. None se a intimação não exige resposta (ex.: mero Conhecimento).

    Lê o DOM e, se o ícone ainda não tiver sido renderizado (coluna "Ações" lazy — ver
    `_acoes_lazy_html`), resolve pelo mesmo endpoint em lote que `urls_aceite` já usa. Sem
    isso, processo grande (típico do coletivo) fazia o prazo sumir em silêncio: a Lista de
    Protocolos aparecia normal, mas o ícone de resposta ainda não tinha carregado.
    """
    oc = page.evaluate(
        "()=>{const a=[...document.querySelectorAll('a')].find(x=>"
        "(x.querySelector('img')?.getAttribute('src')||'').includes('intimacao_peticionar_resposta'));"
        "return a?a.getAttribute('onclick'):'';}"
    )
    m = re.search(r"window\.location\s*=\s*'([^']+)'", oc or "") or \
        re.search(r"window\.open\('([^']+)'", oc or "")
    if m:
        return _abs(m.group(1))
    lazy = _resposta_lazy(page)
    return _abs(lazy) if lazy else None


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
