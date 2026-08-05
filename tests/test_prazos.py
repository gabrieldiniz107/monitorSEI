"""Testes da escadinha de avisos de prazo (Fase 3). Tudo puro, sem I/O."""
from datetime import date

import pytest

from seibot import prazos
from seibot.datas import de_ddmmaaaa, eh_dia_util, proximo_dia_util

LINHA = {"processo": "53500.098046/2026-23", "doc_id": "16067648",
         "oficio_desc": "Ofício 688", "empresa": "Age Telecomunicações S.A",
         "data_limite": "20/08/2026"}


# --- a escadinha ------------------------------------------------------------
@pytest.mark.parametrize("prazo,intervalo", [
    (5, 1), (10, 2), (15, 3), (20, 4), (30, 5),
])
def test_degraus_mapeados(prazo, intervalo):
    assert prazos.intervalo_de(prazo) == intervalo


@pytest.mark.parametrize("prazo,intervalo", [
    (6, 1),    # arredonda para 5
    (9, 1),    # ainda 5
    (12, 2),   # arredonda para 10
    (19, 3),   # arredonda para 15
    (25, 4),   # arredonda para 20
    (45, 5),   # acima do topo → usa 30
])
def test_arredonda_para_o_degrau_inferior(prazo, intervalo):
    assert prazos.intervalo_de(prazo) == intervalo


@pytest.mark.parametrize("prazo", [None, 0, 1, 3, 4])
def test_prazo_curto_ou_desconhecido_avisa_todo_dia(prazo):
    """`None` são as linhas recuperadas pelo backfill (só veio a data). Na dúvida,
    insiste todo dia — perder prazo é pior que avisar demais."""
    assert prazos.intervalo_de(prazo) == 1


# --- quando avisar ----------------------------------------------------------
def _decidir(faltam, prazo_dias, **kw):
    """Monta a decisão para 'faltam N dias', ancorando no vencimento."""
    from datetime import timedelta
    limite = date(2026, 8, 20)
    hoje = limite - timedelta(days=faltam)
    return prazos.decidir("20/08/2026", prazo_dias, hoje, **kw)


def test_cadencia_ancorada_no_vencimento_prazo_20():
    """Prazo 20 → intervalo 4 → avisa quando faltam 20, 16, 12, 8, 4 e 0 dias."""
    avisou = [f for f in range(21) if _decidir(f, 20).avisar]
    assert avisou == [0, 4, 8, 12, 16, 20]


def test_cadencia_diaria_no_prazo_de_5():
    assert [f for f in range(6) if _decidir(f, 5).avisar] == [0, 1, 2, 3, 4, 5]


def test_prazo_arredondado_usa_o_intervalo_do_degrau_inferior():
    """Prazo 22 → degrau 20 → intervalo 4. Como a âncora é o VENCIMENTO, os avisos caem
    em múltiplos de 4 a partir dele — o primeiro sai quando faltam 20 (dois dias após a
    ciência), e não no dia 22. O que importa é que o dia 0 (vencimento) sempre é coberto."""
    avisou = [f for f in range(23) if _decidir(f, 22).avisar]
    assert avisou == [0, 4, 8, 12, 16, 20]
    assert 0 in avisou   # o dia do vencimento nunca pode ficar sem verificação


def test_ultima_chance_e_marcada_uma_vez():
    """A última verificação ANTES do vencimento é o gancho da defesa/dilação."""
    assert _decidir(4, 20).ultima_chance is True
    assert _decidir(8, 20).ultima_chance is False
    assert _decidir(0, 20).ultima_chance is False   # o dia do vencimento é outro caso


def test_dia_do_vencimento_avisa_e_nao_e_vencido():
    d = _decidir(0, 20)
    assert d.avisar and d.faltam == 0 and not d.vencido


def test_vencido_avisa_todo_dia_independente_da_cadencia():
    """Prazo estourado é o pior cenário: insiste diariamente até saírem da raia."""
    assert all(_decidir(-n, 20).avisar for n in range(1, 8))
    assert _decidir(-3, 20).vencido is True


def test_nao_repete_o_aviso_no_mesmo_dia():
    """O comando pode ser rodado à mão depois do cron."""
    assert _decidir(4, 20, ja_avisou_hoje=True).avisar is False
    assert _decidir(-3, 20, ja_avisou_hoje=True).avisar is False


def test_sem_data_limite_nao_ha_o_que_contar():
    assert prazos.decidir("", 20, date(2026, 8, 1)) is None
    assert prazos.decidir("data ruim", 20, date(2026, 8, 1)) is None


# --- mensagens --------------------------------------------------------------
def test_aviso_normal_diz_quantos_dias_faltam():
    m = prazos.formatar_aviso(LINHA, _decidir(8, 20))
    assert "faltam 8 dia(s)" in m and "Age Telecomunicações S.A" in m
    assert "Ofício 688 (16067648)" in m and "20/08/2026" in m


def test_aviso_de_ultima_chance_fala_em_defesa_ou_dilacao():
    m = prazos.formatar_aviso(LINHA, _decidir(4, 20))
    assert "ÚLTIMA" in m and "dilação de prazo" in m


def test_aviso_no_dia_do_vencimento():
    assert "VENCE HOJE" in prazos.formatar_aviso(LINHA, _decidir(0, 20))


def test_aviso_de_vencido_conta_os_dias():
    assert "VENCIDO há 3 dia(s)" in prazos.formatar_aviso(LINHA, _decidir(-3, 20))


def test_parada_deixa_claro_que_nao_e_processo_resolvido():
    """Exigência do usuário: parar de contar ≠ processo resolvido."""
    m = prazos.formatar_parada(LINHA, prazos.PARADA_SAIU_DA_RAIA, "Defesa enviada")
    assert "encerrada pela automação" in m
    assert "não</b> marca o processo como resolvido" in m
    assert "Defesa enviada" in m


def test_sem_card_explica_que_nao_da_para_acompanhar():
    m = prazos.formatar_sem_card(LINHA)
    assert "sem card" in m.lower() and "Criar o card à mão" in m


def test_mensagens_escapam_html():
    linha = {**LINHA, "empresa": "<script>x</script>"}
    for m in (prazos.formatar_aviso(linha, _decidir(4, 20)),
              prazos.formatar_parada(linha, "m"),
              prazos.formatar_sem_card(linha)):
        assert "<script>" not in m and "&lt;script&gt;" in m


# --- dia útil (trava da ciência) --------------------------------------------
def test_eh_dia_util_reconhece_fim_de_semana():
    assert eh_dia_util(date(2026, 8, 7)) is True    # sexta
    assert eh_dia_util(date(2026, 8, 8)) is False   # sábado
    assert eh_dia_util(date(2026, 8, 9)) is False   # domingo
    assert eh_dia_util(date(2026, 8, 10)) is True   # segunda


def test_proximo_dia_util_pula_o_fim_de_semana():
    assert proximo_dia_util(date(2026, 8, 8)) == date(2026, 8, 10)
    assert proximo_dia_util(date(2026, 8, 10)) == date(2026, 8, 10)


def test_de_ddmmaaaa():
    assert de_ddmmaaaa("19/08/2026") == date(2026, 8, 19)
    assert de_ddmmaaaa("") is None


# ---------------------------------------------------------------------------
# Orquestração (monitor.acompanhar_prazos) — consulta a raia ANTES de avisar
# ---------------------------------------------------------------------------
from seibot import monitor
from seibot.models import Intimacao
from seibot.oficio_card import STATUS_AGUARDANDO
from seibot.store import IntimacoesStore

PROC, DOC, CNPJ = "53500.098046/2026-23", "16067648", "36230547000120"


def _store_com_prazo(tmp_path, data_limite="20/08/2026", prazo_dias=20):
    store = IntimacoesStore(str(tmp_path / "t.db"))
    intim = Intimacao(
        processo=PROC, doc_id=DOC, oficio_desc="Ofício 688",
        destinatario="Age Telecomunicações S.A", documento=CNPJ, documento_fmt=CNPJ,
        tipo_destinatario="Pessoa Jurídica", tipo_intimacao="Requerimento de Informações",
        data_expedicao="31/07/2026", situacao="Pendente")
    store.marcar_tratado(intim, data_limite, prazo_dias=prazo_dias,
                         prazo_unidade="dias", oficio_desc="Ofício 688")
    return store


def _cards(status):
    return {(PROC, DOC): {"Title": PROC, "StatusOficio": status}}


def test_avisa_enquanto_esta_na_raia_de_aguardando(tmp_path):
    store = _store_com_prazo(tmp_path)
    enviadas = []
    r = monitor.acompanhar_prazos(store=store, cards=_cards(STATUS_AGUARDANDO),
                                  hoje=date(2026, 8, 16),  # faltam 4 → última chance
                                  enviar=enviadas.append, log=lambda *a: None)
    assert r["avisos"] == 1 and r["paradas"] == 0
    assert "ÚLTIMA" in enviadas[0]


def test_dia_sem_cadencia_nao_avisa(tmp_path):
    store = _store_com_prazo(tmp_path)
    enviadas = []
    r = monitor.acompanhar_prazos(store=store, cards=_cards(STATUS_AGUARDANDO),
                                  hoje=date(2026, 8, 15),  # faltam 5 → fora da cadência
                                  enviar=enviadas.append, log=lambda *a: None)
    assert r["avisos"] == 0 and enviadas == []


def test_saiu_da_raia_para_de_contar_e_avisa_uma_vez(tmp_path):
    """Exigência do usuário: consulta o quadro ANTES de avisar. Se saiu, a mensagem é a
    de parada — nunca mais um lembrete de prazo."""
    store = _store_com_prazo(tmp_path)
    enviadas = []
    hoje = date(2026, 8, 16)   # seria dia de aviso, mas o card saiu da raia
    r = monitor.acompanhar_prazos(store=store, cards=_cards("Defesa enviada"),
                                  hoje=hoje, enviar=enviadas.append, log=lambda *a: None)
    assert r["paradas"] == 1 and r["avisos"] == 0
    assert "encerrada pela automação" in enviadas[0]
    assert "Defesa enviada" in enviadas[0]

    # no dia seguinte não manda mais nada: saiu do acompanhamento
    enviadas.clear()
    r2 = monitor.acompanhar_prazos(store=store, cards=_cards("Defesa enviada"),
                                   hoje=date(2026, 8, 20), enviar=enviadas.append,
                                   log=lambda *a: None)
    assert r2["acompanhando"] == 0 and enviadas == []


def test_sem_card_avisa_o_grupo_e_para(tmp_path):
    store = _store_com_prazo(tmp_path)
    enviadas = []
    r = monitor.acompanhar_prazos(store=store, cards={}, hoje=date(2026, 8, 16),
                                  enviar=enviadas.append, log=lambda *a: None)
    assert r["sem_card"] == 1
    assert "sem card" in enviadas[0].lower()
    assert store.em_acompanhamento() == []


def test_nao_repete_aviso_se_rodar_duas_vezes_no_mesmo_dia(tmp_path):
    store = _store_com_prazo(tmp_path)
    enviadas = []
    args = dict(store=store, cards=_cards(STATUS_AGUARDANDO), hoje=date(2026, 8, 16),
                log=lambda *a: None)
    monitor.acompanhar_prazos(enviar=enviadas.append, **args)
    monitor.acompanhar_prazos(enviar=enviadas.append, **args)
    assert len(enviadas) == 1


def test_sem_prazo_nao_entra_no_acompanhamento(tmp_path):
    """Intimação de 'mero Conhecimento' não tem prazo de resposta."""
    store = _store_com_prazo(tmp_path, data_limite="", prazo_dias=None)
    assert store.em_acompanhamento() == []
