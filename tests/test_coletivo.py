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

    def aceites_no_dom(self, page):
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
        for nome in ("urls_aceite", "aceites_no_dom", "dar_ciencia", "abrir_processo"):
            monkeypatch.setattr(real, nome, getattr(fake, nome))
        return fake
    return instalar


class _StoreFake:
    def __init__(self):
        self.tratados = []

    def marcar_tratado(self, intim, data_limite="", **kw):
        self.tratados.append(intim.chave)


_ACEITE = [{"url": "u1", "num": "999", "principal": True}]


def test_uma_confirmacao_cobre_todos_os_destinatarios(processo_fake):
    """Confirmar UM documento cumpre a intimação inteira — a URL do aceite carrega todos os
    `id_intimacao[]`. Validado no ofício 693 (07/08/2026): 1 confirmação, 8 certidões."""
    g = _grupo(*[_intim(str(n)) for n in range(9)])
    page = _PageFake([[]])                      # a conferência pós-ciência não acha sobra
    processo_fake(page)
    store = _StoreFake()

    assert coletivo._dar_ciencia_uma_vez(page, g, _ACEITE, store, lambda *_: None) == 1
    assert page.cliques == ["u1"]               # UMA vez, não N
    assert len(store.tratados) == 9             # o checkpoint cobre as NOVE empresas


def test_nao_repete_a_ciencia_mesmo_com_icone_sobrando(processo_fake):
    """Antes isto era um laço que reconfirmava até zerar. Cada releitura dispara um POST por
    documento no endpoint das Ações, e no ofício 682 (138 linhas, 16 placeholders) isso levou
    dezenas de minutos até ser interrompido à mão. Agora avisa e para."""
    g = _grupo(*[_intim(str(n)) for n in range(9)])
    page = _PageFake([_ACEITE])                 # ainda há ícone depois da confirmação
    processo_fake(page)
    avisos = []

    assert coletivo._dar_ciencia_uma_vez(page, g, _ACEITE, _StoreFake(), avisos.append) == 1
    assert page.cliques == ["u1"]
    assert any("NÃO vou repetir" in a for a in avisos)


def test_alvo_da_ciencia_e_o_documento_do_oficio(processo_fake):
    g = _grupo(_intim("1"), _intim("2"))
    page = _PageFake([[]])
    processo_fake(page)
    aceites = [{"url": "outro", "num": "111", "principal": False},
               {"url": "certo", "num": g.doc_id, "principal": False}]

    coletivo._dar_ciencia_uma_vez(page, g, aceites, _StoreFake(), lambda *_: None)
    assert page.cliques == ["certo"]


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


# ------------------------------------------- Pendente sem ícone de aceite é contradição
def test_pendente_sem_icone_de_aceite_recarrega_e_depois_aborta(processo_fake):
    """Ofícios 682 e 666 (lote de 07/08/2026): `urls_aceite` voltou vazio com destinatários
    ainda Pendentes. O código seguia como "ciência já dada" e quebrava adiante em "ofício
    não achado na Lista de Protocolos" — deixando a intimação Pendente sem ninguém ter dado
    ciência. Agora relê a página e, se insistir, aborta alto."""
    g = _grupo(*[_intim(str(n)) for n in range(3)])          # todos Pendente
    page = _PageFake([[], [], []])
    processo_fake(page)
    with pytest.raises(RuntimeError, match="nenhum ícone de aceite após"):
        coletivo._aceites_de_pendente(page, g, lambda *_: None)


def test_pendente_sem_icone_aceita_o_que_a_releitura_trouxer(processo_fake):
    g = _grupo(*[_intim(str(n)) for n in range(3)])
    page = _PageFake([[], _ACEITE])          # a 2ª leitura já traz o ícone
    processo_fake(page)
    assert coletivo._aceites_de_pendente(page, g, lambda *_: None) == _ACEITE


def test_sem_pendente_e_sem_icone_segue_normal(processo_fake):
    """Coletivo já cumprido: vazio é o estado correto, não relê nem aborta."""
    from dataclasses import replace
    g = _grupo(*[replace(_intim(str(n)), situacao="Cumprida por Consulta Direta")
                 for n in range(3)])
    page = _PageFake([[]])
    processo_fake(page)
    assert coletivo._aceites_de_pendente(page, g, lambda *_: None) == []


def test_navegacao_no_meio_da_leitura_das_acoes_e_retentada(monkeypatch):
    """Ofício 663 (07/08/2026): `urls_aceite` levantou "Execution context was destroyed" —
    a página navegou enquanto o loader do SEI buscava as Ações. Reabrir resolve."""
    import seibot.processo as real
    g = _grupo(_intim("1"), _intim("2"))
    chamadas = {"n": 0}

    def instavel(page):
        chamadas["n"] += 1
        if chamadas["n"] == 1:
            raise RuntimeError("Page.evaluate: Execution context was destroyed, "
                               "most likely because of a navigation")
        return _ACEITE

    monkeypatch.setattr(real, "urls_aceite", instavel)
    monkeypatch.setattr(real, "abrir_processo", lambda *a, **k: None)
    assert coletivo._aceites_de_pendente(None, g, lambda *_: None) == _ACEITE


def test_erro_alheio_ao_ler_as_acoes_nao_e_engolido(monkeypatch):
    """Só erro de navegação é retentável — o resto tem de subir, não virar 'sem aceite'."""
    import seibot.processo as real
    g = _grupo(_intim("1"), _intim("2"))

    def quebra(page):
        raise RuntimeError("browser has been closed")

    monkeypatch.setattr(real, "urls_aceite", quebra)
    monkeypatch.setattr(real, "abrir_processo", lambda *a, **k: None)
    with pytest.raises(RuntimeError, match="browser has been closed"):
        coletivo._aceites_de_pendente(None, g, lambda *_: None)
