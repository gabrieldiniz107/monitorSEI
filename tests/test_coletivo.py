"""Testes da Fase 4 (ofício coletivo): seleção de candidatos e laço de ciência."""
from dataclasses import replace

import pytest

from seibot import coletivo
from seibot.classificar import agrupar_por_oficio
from seibot.models import Intimacao
from seibot.store import IntimacoesStore


def _intim(cnpj, situacao="Pendente", doc_id="15960502"):
    return Intimacao(
        processo="53500.069114/2026-47", doc_id=doc_id, oficio_desc="Ofício 600",
        destinatario=f"Empresa {cnpj}", documento=cnpj, documento_fmt=cnpj,
        tipo_destinatario="Pessoa Jurídica", tipo_intimacao="Intimação para mero Conhecimento",
        data_expedicao="14/07/2026", situacao=situacao,
    )


def _grupo(*intims):
    return agrupar_por_oficio(list(intims))[0]


# --------------------------------------------------------------- seleção
def test_individual_nao_e_da_fase_4():
    m = coletivo.motivo_nao_candidato(_grupo(_intim("111")))
    assert m and "individual" in m


def test_coletivo_pendente_e_candidato():
    assert coletivo.motivo_nao_candidato(_grupo(_intim("111"), _intim("222"))) is None


def test_coletivo_com_situacao_MISTA_ainda_e_candidato():
    """O caso real: alguém do Jurídico já deu ciência por uma empresa e as outras ficaram
    Pendentes. Recusar aqui deixaria as demais sem ciência para sempre."""
    g = _grupo(_intim("111", "Cumprida por Consulta Direta"), _intim("222"), _intim("333"))
    assert coletivo.motivo_nao_candidato(g) is None


def test_coletivo_sem_nenhum_pendente_e_recusado_com_as_situacoes_no_motivo():
    g = _grupo(_intim("111", "Respondida"), _intim("222", "Cumprida por Consulta Direta"))
    m = coletivo.motivo_nao_candidato(g)
    assert m and "nenhum destinatário Pendente" in m
    assert "Respondida" in m and "Cumprida por Consulta Direta" in m


def test_ja_tratado_e_recusado():
    m = coletivo.motivo_nao_candidato(_grupo(_intim("111"), _intim("222")), ja_tratado=True)
    assert m and "já tratado" in m


def test_selecionar_candidatos_ignora_o_ja_tratado_por_completo(tmp_path):
    store = IntimacoesStore(str(tmp_path / "t.db"))
    tratado = _grupo(_intim("111", doc_id="1"), _intim("222", doc_id="1"))
    novo = _grupo(_intim("333", doc_id="2"), _intim("444", doc_id="2"))
    for i in tratado.destinatarios:
        store.marcar_tratado(i, "")

    escolhidos = coletivo.selecionar_candidatos([tratado, novo], store)
    assert [g.doc_id for g in escolhidos] == ["2"]


def test_grupo_parcialmente_tratado_continua_candidato(tmp_path):
    """Só o ofício INTEIRO tratado sai da fila: se uma empresa ficou de fora (falha no meio),
    o ofício precisa voltar."""
    store = IntimacoesStore(str(tmp_path / "t.db"))
    g = _grupo(_intim("111"), _intim("222"))
    store.marcar_tratado(g.destinatarios[0], "")
    assert coletivo.selecionar_candidatos([g], store) == [g]


# --------------------------------------------------------------- laço de ciência
class _PageFake:
    """Simula a página: `roteiro` é a lista de aceites devolvida a cada leitura."""
    def __init__(self, roteiro):
        self.roteiro = list(roteiro)
        self.cliques = []

    def proximo(self):
        return self.roteiro.pop(0) if self.roteiro else []


class _ProcessoFake:
    def __init__(self, page):
        self.page = page

    def urls_aceite(self, page):
        return page.proximo()

    def dar_ciencia(self, page, url):
        page.cliques.append(url)

    def abrir_processo(self, page, url, tentativas=3):
        pass


@pytest.fixture
def processo_fake(monkeypatch):
    def instalar(page):
        fake = _ProcessoFake(page)
        import seibot.processo as real
        for nome in ("urls_aceite", "dar_ciencia", "abrir_processo"):
            monkeypatch.setattr(real, nome, getattr(fake, nome))
        return fake
    return instalar


class _StoreFake:
    def __init__(self):
        self.tratados = []

    def marcar_tratado(self, intim, data_limite="", **kw):
        self.tratados.append(intim.chave)


_ACEITE = [{"url": "u1", "num": "999", "principal": True}]


def test_uma_ciencia_cobre_todos_para_o_laco_na_primeira_volta(processo_fake):
    g = _grupo(*[_intim(str(n)) for n in range(9)])
    page = _PageFake([_ACEITE, []])       # depois de 1 confirmação, some tudo
    processo_fake(page)
    store = _StoreFake()

    assert coletivo._dar_ciencia_de_todos(page, g, store, lambda *_: None) == 1
    # o checkpoint cobre as NOVE empresas, não só a primeira
    assert len(store.tratados) == 9


def test_ciencia_por_destinatario_repete_ate_zerar(processo_fake):
    g = _grupo(_intim("1"), _intim("2"), _intim("3"))
    page = _PageFake([_ACEITE, _ACEITE, _ACEITE, []])
    processo_fake(page)

    assert coletivo._dar_ciencia_de_todos(page, g, _StoreFake(), lambda *_: None) == 3
    assert page.cliques == ["u1", "u1", "u1"]


def test_checkpoint_e_gravado_uma_unica_vez(processo_fake):
    g = _grupo(_intim("1"), _intim("2"))
    page = _PageFake([_ACEITE, _ACEITE, []])
    processo_fake(page)
    store = _StoreFake()

    coletivo._dar_ciencia_de_todos(page, g, store, lambda *_: None)
    assert len(store.tratados) == 2   # 2 empresas × 1 checkpoint, não 2 × 2 voltas


def test_pagina_que_nunca_zera_aborta_no_teto(processo_fake):
    """Sem teto isto seria um laço infinito clicando em 'confirmar' — o pior cenário
    possível numa ação irreversível."""
    g = _grupo(_intim("1"), _intim("2"))
    page = _PageFake([_ACEITE] * 20)
    processo_fake(page)

    with pytest.raises(RuntimeError, match="laço de ciência excedeu"):
        coletivo._dar_ciencia_de_todos(page, g, _StoreFake(), lambda *_: None)
    assert len(page.cliques) == len(g.destinatarios) + coletivo.FOLGA_CIENCIA


def test_sem_aceite_nenhum_nao_clica(processo_fake):
    g = _grupo(_intim("1"), _intim("2"))
    page = _PageFake([[]])
    processo_fake(page)
    assert coletivo._dar_ciencia_de_todos(page, g, _StoreFake(), lambda *_: None) == 0
    assert page.cliques == []


# --------------------------------------------------------------- mensagem do Teams
class _Prazo:
    data_limite, tipo, dias, unidade = "19/08/2026", "Impugnação", 20, "dias úteis"


def _msg(**kw):
    g = _grupo(*[_intim(str(n)) for n in range(3)])
    base = dict(clientes=None, prazo=None, n_anexos=2, link="", resumo_txt="", ciencias=0)
    base.update(kw)
    return coletivo.msg_html(g, base.pop("clientes"), base.pop("prazo"),
                             base.pop("n_anexos"), base.pop("link"), **base)


def test_mensagem_traz_link_da_pasta_sem_escapar_a_url():
    msg = _msg(link="https://sharepoint/x?a=1&b=2", ciencias=1)
    assert '<a href="https://sharepoint/x?a=1&b=2">' in msg
    assert "ciência dada" in msg
    assert "\n" not in msg


def test_mensagem_sem_ciencia_nao_afirma_que_deu_ciencia():
    assert "ciência dada" not in _msg(link="https://x")


def test_prazo_em_coletivo_e_destacado_como_excecao():
    msg = _msg(prazo=_Prazo())
    assert "TEM prazo" in msg and "19/08/2026" in msg
    assert "controlar à mão" in msg


def test_sem_prazo_nao_inventa_linha_de_prazo():
    assert "prazo" not in _msg().lower()


def test_resumo_entra_escapado():
    assert "&lt;b&gt;" in _msg(resumo_txt="<b>x</b>")


# --------------------------------------------------- clique de ciência sem desfecho
class _SessFake:
    def __init__(self, page):
        self.page = page
        self.context = None


def test_clique_sem_desfecho_grava_checkpoint_e_vira_falha_pos_ciencia(processo_fake,
                                                                       monkeypatch):
    """Incidente 07/08/2026 (coletivo 693): o click() estourou esperando a navegação DEPOIS
    de já ter clicado — a ciência entrou. Como o erro subiu como falha comum, nada foi
    gravado e o ofício sairia da seleção em silêncio (deixa de ter destinatário Pendente).
    """
    import seibot.processo as real
    from seibot.tratativa import TratativaIncompleta

    g = _grupo(*[_intim(str(n)) for n in range(9)])
    # duas leituras: a do `tratar_coletivo` (captura os docs) e a do laço de ciência
    page = _PageFake([_ACEITE, _ACEITE])
    processo_fake(page)

    def estoura(page_, url):
        raise real.CienciaIncerta("clique em #sbmAceitarIntimacao sem desfecho confirmado")
    monkeypatch.setattr(real, "dar_ciencia", estoura)

    store = _StoreFake()
    with pytest.raises(TratativaIncompleta):
        coletivo.tratar_coletivo(_SessFake(page), None, g, None, store, None,
                                 dar_ciencia=True, log=lambda *_: None)
    # as NOVE empresas ficam registradas: o prazo já corre para todas
    assert len(store.tratados) == 9
