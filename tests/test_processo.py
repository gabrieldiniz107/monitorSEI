"""Testes dos parsers puros do Increment 3 (anexos + prazo)."""
from seibot.processo import Prazo, anexos_da_intimacao, extrair_anexos, parse_prazo

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


def test_parse_prazo_defesa_preliminar():
    p = parse_prazo("Defesa Preliminar (15 Dias) - Data Limite: 30/07/2026")
    assert p == Prazo(tipo="Defesa Preliminar", dias=15, data_limite="30/07/2026")


def test_parse_prazo_variacao_espacos():
    p = parse_prazo("Manifestação  ( 10 Dias ) - Data Limite:  05/08/2026")
    assert p.dias == 10 and p.data_limite == "05/08/2026"


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
