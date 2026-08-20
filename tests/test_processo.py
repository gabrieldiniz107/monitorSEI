"""Testes dos parsers puros do Increment 3 (anexos + prazo)."""
import pytest

from seibot.processo import (Prazo, anexos_da_intimacao, eh_pdf, extrair_anexos,
                             extrair_texto_oficio, parse_prazo)

# Lista de Protocolos REAL do proc 53508.003179/2026-50 (após a ciência, 2026-07-20)
_PROTOCOLOS = {
    "15981049": {"tipo": "Requerimento de Informações", "url": "u1"},
    "15981037": {"tipo": "Planilha de Avaliação de Maturidade Cibernética", "url": "u2"},
    "15981104": {"tipo": "Ofício 70", "url": "u3"},
    "15988916": {"tipo": "Certidão de Intimação Cumprida", "url": "u4"},
}


# documentos DA INTIMAÇÃO (nºs dos ícones de aceite) do proc 53508.003179/2026-50
_DOCS_INTIMACAO = ["15981104", "15981049", "15981037"]


def test_anexos_sao_os_documentos_da_intimacao_menos_o_oficio():
    assert anexos_da_intimacao(_PROTOCOLOS, "15981104", _DOCS_INTIMACAO) == \
        ["15981049", "15981037"]


def test_anexos_ignoram_documentos_do_processo_fora_da_intimacao():
    """Regressão do proc 53539.000753/2026-51 (21/07/2026): a Lista de Protocolos tinha 4
    documentos, mas a intimação era só o Ofício 268 + o Despacho Decisório 476. 'Consulta
    CNPJ' e 'Consulta' são internos da Anatel e NÃO podem ir para o cliente."""
    protos = {
        "15987435": {"tipo": "Despacho Decisório 476", "url": "u1"},
        "15987480": {"tipo": "Ofício 268", "url": "u2"},
        "15987610": {"tipo": "Consulta CNPJ", "url": "u3"},
        "15987617": {"tipo": "Consulta", "url": "u4"},
    }
    assert anexos_da_intimacao(protos, "15987480", ["15987435", "15987480"]) == ["15987435"]


def test_anexos_nao_dependem_do_texto_do_oficio():
    """O Ofício 70 citava só 1 dos 2 anexos — os ícones de aceite mandam; citados ordenam."""
    assert anexos_da_intimacao(_PROTOCOLOS, "15981104", _DOCS_INTIMACAO, ["15981037"]) == \
        ["15981037", "15981049"]


def test_anexos_citados_apenas_reordenam():
    r = anexos_da_intimacao(_PROTOCOLOS, "15981104", _DOCS_INTIMACAO, ["15981049"])
    assert r[0] == "15981049" and sorted(r) == ["15981037", "15981049"]


def test_anexos_sem_icones_de_aceite_caem_para_os_citados():
    """Processo já cumprido: os ícones de aceite somem, sobra o texto do ofício."""
    assert anexos_da_intimacao(_PROTOCOLOS, "15981104", [], ["15981037"]) == ["15981037"]


def test_anexos_sem_icones_e_sem_citados_nao_manda_nada():
    """Melhor e-mail só com o ofício do que com o processo inteiro do cliente."""
    assert anexos_da_intimacao(_PROTOCOLOS, "15981104", [], []) == []


def test_anexos_ignoram_certidao_e_numero_fora_da_lista():
    """Certidão de Intimação Cumprida é prova interna da ciência; nº inexistente é ignorado."""
    assert anexos_da_intimacao(
        _PROTOCOLOS, "15981104", ["15988916", "99999999", "15981049"]) == ["15981049"]


def test_processo_so_com_oficio_nao_tem_anexos():
    assert anexos_da_intimacao({"15981104": {"tipo": "Ofício 70"}}, "15981104",
                               ["15981104"]) == []


# trecho REAL do Ofício 498 (entidades HTML como vêm do SEI)
_OFICIO_COM_ANEXOS = (
    "<p>&nbsp; Atenciosamente,</p><p>&nbsp;&nbsp; Anexos:</p>"
    "<p>I - Ata do Resultado Definitivo Benef&iacute;cio Fiscal (SEI n&ordm;&nbsp; 15963829 ).</p>"
    "<p>II - Manual de Benef&iacute;cio Fiscal (SEI n&ordm;&nbsp; 15963779 ).</p>"
)
_OFICIO_SEM_ANEXOS = "<p>Prezado, comunicamos o teor da decis&atilde;o. Atenciosamente.</p>"


def test_extrai_anexos_com_entidades_html():
    assert extrair_anexos(_OFICIO_COM_ANEXOS) == ["15963829", "15963779"]


def test_oficio_sem_anexos_retorna_vazio():
    assert extrair_anexos(_OFICIO_SEM_ANEXOS) == []


def test_anexos_nao_repetem():
    html = _OFICIO_COM_ANEXOS + "<p>reitera (SEI nº 15963829).</p>"
    assert extrair_anexos(html) == ["15963829", "15963779"]


# --- ofício HTML vs PDF (correção 2026-07-22, rascunho da Maxxnet 16003317) -------------
def test_eh_pdf_detecta_magic_number():
    assert eh_pdf(b"%PDF-1.4\n...") is True
    assert eh_pdf(b"<html>Of\xedcio</html>") is False


def test_extrair_texto_oficio_html_decodifica_iso8859():
    # ofício gerado no SEI: HTML ISO-8859-1 (0xed = í) → decodifica, sem chamar pypdf
    html = "<p>Of\xedcio 70 requerimento</p>".encode("iso-8859-1")
    def _nao_deveria(_):  # pdf_extractor não pode ser chamado p/ HTML
        raise AssertionError("pdf_extractor chamado para HTML")
    txt = extrair_texto_oficio(html, pdf_extractor=_nao_deveria)
    assert "Ofício 70" in txt


def test_extrair_texto_oficio_pdf_usa_extrator():
    # ofício servido como PDF (Notificação de Lançamento): roteia para o extrator de PDF,
    # NÃO decodifica o binário como texto (era o bug que gerava resumo-lixo).
    pdf = b"%PDF-1.4 conteudo binario \xff\xfe"
    txt = extrair_texto_oficio(pdf, pdf_extractor=lambda b: "TEXTO DO PDF")
    assert txt == "TEXTO DO PDF"


def test_parse_prazo_defesa_preliminar():
    p = parse_prazo("Defesa Preliminar (15 Dias) - Data Limite: 30/07/2026")
    assert p == Prazo(tipo="Defesa Preliminar", dias=15, data_limite="30/07/2026")


def test_parse_prazo_variacao_espacos():
    p = parse_prazo("Manifestação  ( 10 Dias ) - Data Limite:  05/08/2026")
    assert p.dias == 10 and p.data_limite == "05/08/2026"


def test_parse_prazo_dias_uteis():
    # Regressão (2026-07-22, Cobrança de Crédito Tributário da Maxxnet): o regex antigo,
    # preso em "Dias)", devolvia None p/ "20 Dias Úteis" → bot dizia "sem prazo de resposta"
    # apesar de a Data Limite estar legível no #selTipoResposta.
    p = parse_prazo("Impugnação (20 Dias Úteis) - Data Limite: 19/08/2026")
    assert p == Prazo(tipo="Impugnação", dias=20, data_limite="19/08/2026",
                      unidade="dias úteis")


def test_parse_prazo_dias_corridos_e_singular():
    assert parse_prazo("Recurso (10 Dias Corridos) - Data Limite: 01/09/2026").unidade == "dias corridos"
    assert parse_prazo("X (1 Dia Útil) - Data Limite: 23/07/2026").unidade == "dia útil"


def test_parse_prazo_dias_simples_unidade_padrao():
    # sem qualificador, unidade continua "dias" (compatível com a construção antiga do Prazo)
    p = parse_prazo("Defesa (15 Dias) - Data Limite: 30/07/2026")
    assert p.unidade == "dias" and p == Prazo(tipo="Defesa", dias=15, data_limite="30/07/2026")


def test_parse_prazo_sem_prazo_retorna_none():
    assert parse_prazo("Público") is None
    assert parse_prazo("") is None


# --- abrir_processo: resiliência a navegação no meio do carregamento -----------------
# Regressão do proc 53539.000753/2026-51 (21/07/2026): "Execution context was destroyed,
# most likely because of a navigation" derrubou a tratativa antes da ciência.
from seibot import processo as _p  # noqa: E402

_ERRO_NAV = "Page.evaluate: Execution context was destroyed, most likely because of a navigation"


class _FakePage:
    """Page mínima: falha nos N primeiros `evaluate` com o erro indicado."""

    def __init__(self, falhas=0, erro=_ERRO_NAV, altura=900):
        self.falhas, self.erro, self.altura = falhas, erro, altura
        self.gotos, self.scrolls = [], []

    def goto(self, url, **kw):
        self.gotos.append(url)

    def wait_for_load_state(self, *a, **kw):
        pass

    def wait_for_timeout(self, ms):
        pass

    def evaluate(self, expr, arg=None):
        if self.falhas > 0:
            self.falhas -= 1
            raise RuntimeError(self.erro)
        if "scrollTo" in expr:
            self.scrolls.append(arg)
            return None
        return self.altura


def test_abrir_processo_retenta_quando_a_pagina_navega():
    page = _FakePage(falhas=1)
    _p.abrir_processo(page, "/proc?id=1")
    assert len(page.gotos) == 2          # reabriu
    assert page.scrolls == [0, 300, 600, 900]


def test_abrir_processo_nao_retenta_erro_alheio():
    page = _FakePage(falhas=1, erro="boom qualquer")
    try:
        _p.abrir_processo(page, "/proc?id=1")
        assert False, "deveria ter propagado"
    except RuntimeError as e:
        assert "boom" in str(e)
    assert len(page.gotos) == 1          # não retentou


def test_abrir_processo_desiste_apos_as_tentativas():
    page = _FakePage(falhas=99)
    try:
        _p.abrir_processo(page, "/proc?id=1", tentativas=3)
        assert False, "deveria ter propagado"
    except RuntimeError as e:
        assert "Execution context" in str(e)
    assert len(page.gotos) == 3


def test_scroll_acompanha_pagina_que_cresce_com_lazy_load():
    page = _FakePage(altura=300)

    class _Cresce(_FakePage):
        def evaluate(self, expr, arg=None):
            if "scrollTo" in expr:
                self.scrolls.append(arg)
                return None
            self.altura = min(self.altura + 300, 1200)   # cresce enquanto rola
            return self.altura

    page = _Cresce(altura=300)
    _p.abrir_processo(page, "/proc?id=1")
    assert page.scrolls[-1] >= 1200      # chegou ao fim da página já crescida


def test_scroll_tem_teto_de_passos():
    class _Infinita(_FakePage):
        def evaluate(self, expr, arg=None):
            if "scrollTo" in expr:
                self.scrolls.append(arg)
                return None
            self.altura += 10_000        # nunca alcança o fim
            return self.altura

    page = _Infinita()
    _p.abrir_processo(page, "/proc?id=1")
    assert len(page.scrolls) == _p._MAX_PASSOS_SCROLL


# --- baixar_como_pdf: HTML gerado no SEI vira PDF; PDF externo passa cru -------------
# Regressão do rascunho da SITELBRA (proc 53500.064050/2024-26, 2026-07-22): o Despacho
# Decisório e o Informe 17 (documentos gerados no SEI = HTML) foram salvos como .pdf e
# NÃO abriam. Só o Extrato de Lançamentos (upload = PDF de verdade) abria.
class _FakeResp:
    def __init__(self, body):
        self._body, self.status = body, 200

    def body(self):
        return self._body


class _FakeReq:
    def __init__(self, body):
        self._body = body

    def get(self, url, **kw):
        return _FakeResp(self._body)


class _FakeContext:
    def __init__(self, body):
        self.request = _FakeReq(body)


class _FakePagePdf:
    def __init__(self):
        self.pdf_gotos = []

    def goto(self, url, **kw):
        self.pdf_gotos.append(url)

    def wait_for_timeout(self, ms):
        pass

    def pdf(self, **kw):
        return b"%PDF-1.7 renderizado"


def test_baixar_como_pdf_pdf_externo_passa_cru():
    """Extrato de Lançamentos (upload) já é PDF → devolve os bytes crus, sem renderizar."""
    page = _FakePagePdf()
    ctx = _FakeContext(b"%PDF-1.5 conteudo real do extrato")
    out = _p.baixar_como_pdf(page, ctx, "/doc?id=15996728")
    assert out == b"%PDF-1.5 conteudo real do extrato"
    assert page.pdf_gotos == []          # não renderizou


def test_baixar_como_pdf_html_gerado_no_sei_e_renderizado():
    """Despacho/Informe (gerados no SEI) vêm em HTML → renderiza via page.pdf()."""
    page = _FakePagePdf()
    ctx = _FakeContext(b"<html><body>Despacho Decisorio 14/2025</body></html>")
    out = _p.baixar_como_pdf(page, ctx, "/doc?id=13227283")
    assert out == b"%PDF-1.7 renderizado"    # virou PDF de verdade
    assert page.pdf_gotos                     # navegou para renderizar


# ---------------------------------------------------------------------------
# Ícones de aceite: DOM + lazy-load da coluna "Ações"
#
# Achado de 2026-08-07 (coletivo 693, proc 53500.101985/2026-62): a coluna "Ações" não vem
# no HTML — é carregada por AJAX, um documento por vez, em cadeia. Num processo com ~105
# documentos a cadeia não termina antes de o `abrir_processo` ler a página, e `urls_aceite`
# devolvia [] ⇒ o bot concluía "ciência já dada" e não tinha por onde entrar.
# ---------------------------------------------------------------------------
_ACEITE_URL = ("https://sei.anatel.gov.br/sei/controlador_externo.php?"
               "acao=md_pet_intimacao_usu_ext_confirmar_aceite&id_documento=18009400"
               "&id_intimacao[]=330635&id_intimacao[]=330650")


class _PageAceites:
    """Devolve o resultado do JS do DOM e o do lazy conforme o script chamado."""

    def __init__(self, dom, lazy):
        self._dom, self._lazy = dom, lazy
        self.chamadas = 0

    def evaluate(self, script, *a):
        self.chamadas += 1
        return self._lazy if "md-pet-acao-lazy" in script else self._dom


def test_urls_aceite_usa_o_dom_quando_os_icones_ja_renderizaram():
    page = _PageAceites([{"url": "/x?confirmar_aceite", "num": "16075320", "principal": True}],
                        [])
    assert _p.urls_aceite(page) == [
        {"url": "/x?confirmar_aceite", "num": "16075320", "principal": True}]


def test_urls_aceite_resolve_o_lazy_quando_o_dom_esta_vazio():
    """O caso do 693: nenhum ícone no DOM, mas o endpoint devolve os botões."""
    page = _PageAceites([], [
        {"html": f"<a onclick=\"infraAbrirJanelaModal('{_ACEITE_URL}',900,470)\">"
                 "<img src='.../intimacao_nao_cumprida_doc_anexo.svg'></a>",
         "num": "16075320"},
    ])
    achados = _p.urls_aceite(page)
    assert achados == [{"url": _ACEITE_URL, "num": "16075320", "principal": False}]


def test_urls_aceite_nao_duplica_o_que_o_dom_ja_trouxe():
    dom = [{"url": _ACEITE_URL, "num": "16075320", "principal": True}]
    lazy = [{"html": f"<a onclick=\"infraAbrirJanelaModal('{_ACEITE_URL}')\"></a>",
             "num": "16075320"}]
    assert len(_p.urls_aceite(_PageAceites(dom, lazy))) == 1


def test_urls_aceite_ignora_botao_que_nao_e_de_aceite():
    """A coluna Ações também traz ícones de resposta/certidão — só o aceite interessa."""
    lazy = [{"html": "<a onclick=\"infraAbrirJanelaModal('/x?acao=outra_coisa')\"></a>",
             "num": "999"}]
    assert _p.urls_aceite(_PageAceites([], lazy)) == []


def test_urls_aceite_sobrevive_a_falha_do_lazy():
    """Falha de rede no endpoint não pode derrubar a tratativa — devolve o que o DOM tinha."""
    class _Quebrado(_PageAceites):
        def evaluate(self, script, *a):
            if "md-pet-acao-lazy" in script:
                raise RuntimeError("net::ERR_ABORTED")
            return self._dom

    page = _Quebrado([{"url": "/y?confirmar_aceite", "num": "1", "principal": False}], [])
    assert _p.urls_aceite(page) == [{"url": "/y?confirmar_aceite", "num": "1",
                                     "principal": False}]


_RESPOSTA_URL = ("https://sei.anatel.gov.br/sei/controlador_externo.php?"
                 "acao=md_pet_responder_intimacao_usu_ext&id_documento=18009400")


def test_url_peticionar_resposta_usa_o_dom_quando_o_icone_ja_renderizou():
    page = _PageAceites(f"window.location = '{_RESPOSTA_URL}'", [])
    assert _p.url_peticionar_resposta(page) == _RESPOSTA_URL


def test_url_peticionar_resposta_resolve_o_lazy_quando_o_dom_ainda_nao_carregou():
    """Mesma classe de bug do 693, mas no ícone de RESPOSTA — nunca resolvida antes: o
    coletivo tratava normalmente (ciência + pasta), mas ficava sem prazo e, por isso, sem
    card (a criação do card do coletivo é condicionada a haver prazo)."""
    page = _PageAceites("", [
        {"html": f"<a onclick=\"window.location = '{_RESPOSTA_URL}'\">"
                 "<img src='.../intimacao_peticionar_resposta.svg'></a>",
         "num": "16075320"},
    ])
    assert _p.url_peticionar_resposta(page) == _RESPOSTA_URL


def test_url_peticionar_resposta_none_quando_nao_ha_icone_em_lugar_nenhum():
    """Intimação que não exige resposta (ex.: mero Conhecimento) — None é o valor certo,
    não uma falha a ser resolvida pelo lazy."""
    page = _PageAceites("", [])
    assert _p.url_peticionar_resposta(page) is None


def test_escolher_aceite_prefere_o_documento_do_oficio():
    """No 693 os 4 ícones vieram com principal=False — o casamento por doc_id é o que resta."""
    aceites = [{"url": "a", "num": "16075316", "principal": False},
               {"url": "b", "num": "16075320", "principal": False}]
    assert _p.escolher_aceite(aceites, "16075320")["url"] == "b"


def test_escolher_aceite_cai_para_o_principal_e_depois_para_o_primeiro():
    aceites = [{"url": "a", "num": "111", "principal": False},
               {"url": "b", "num": "222", "principal": True}]
    assert _p.escolher_aceite(aceites, "999")["url"] == "b"       # doc_id não casa
    sem_principal = [{"url": "a", "num": "111", "principal": False}]
    assert _p.escolher_aceite(sem_principal, "999")["url"] == "a"
    assert _p.escolher_aceite([], "999") is None


class _ReqInstavel:
    """Falha nas primeiras chamadas e devolve o conteúdo na última."""
    def __init__(self, falhas, body=b"%PDF-ok"):
        self.falhas, self._body, self.chamadas = falhas, body, 0

    def get(self, url, **kw):
        self.chamadas += 1
        if self.chamadas <= self.falhas:
            raise RuntimeError("APIRequestContext.get: Request timed out after 30000ms")
        return _FakeResp(self._body)


def test_baixar_retenta_download_que_estourou(monkeypatch):
    """Visto ao vivo no Ofício 693 (07/08/2026): documento grande passa do timeout padrão.
    Falhar aqui é caro — é depois da ciência, com o prazo já correndo."""
    monkeypatch.setattr(_p.time, "sleep", lambda s: None)
    ctx = type("C", (), {})()
    ctx.request = _ReqInstavel(falhas=2)
    assert _p.baixar(ctx, "/doc?id=1") == b"%PDF-ok"
    assert ctx.request.chamadas == 3


def test_baixar_desiste_e_diz_quantas_tentou(monkeypatch):
    monkeypatch.setattr(_p.time, "sleep", lambda s: None)
    ctx = type("C", (), {})()
    ctx.request = _ReqInstavel(falhas=9)
    with pytest.raises(RuntimeError, match="falhou após 3 tentativas"):
        _p.baixar(ctx, "/doc?id=1")


def test_anexos_do_coletivo_saem_so_do_texto_do_oficio():
    """Regra do COLETIVO (decisão do usuário, 07/08/2026), oposta à do individual.

    Proc 53500.101985/2026-62, Ofício 693: o SEI empacotou 3 anexos na intimação, mas a
    Planilha "Tabela ISPs/Domínios" (16075319) não é do ofício e não pode ir ao cliente. O
    texto do ofício citava exatamente os 2 corretos. `coletivo._apos_ciencia` passa
    docs_intimacao=None justamente para que só os citados entrem.
    """
    protos = {
        "16075316": {"tipo": "Ofício SEI Nº 41178/2026/MF", "url": "u1"},
        "16075317": {"tipo": "Planilha - Tabela Domínios", "url": "u2"},
        "16075319": {"tipo": "Planilha - Tabela ISPs/Domínios", "url": "u3"},
        "16075320": {"tipo": "Ofício 693 - Notificação Prestadoras", "url": "u4"},
    }
    citados = ["16075316", "16075317"]
    assert anexos_da_intimacao(protos, "16075320", None, citados) == citados
    # e a regra do individual, intocada, continua trazendo os 3 documentos da intimação
    docs = ["16075316", "16075317", "16075319", "16075320"]
    assert sorted(anexos_da_intimacao(protos, "16075320", docs)) == \
        ["16075316", "16075317", "16075319"]
