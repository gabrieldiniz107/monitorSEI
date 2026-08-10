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
# Vencimento de referência: 20/08/2026 é uma QUINTA. Datas conferidas no calendário.
VENC = "20/08/2026"


def _dias_que_avisam(data_limite, prazo_dias, ate=30):
    """Datas em que o aviso sai, da mais antiga para a mais recente."""
    from datetime import timedelta
    lim = de_ddmmaaaa(data_limite)
    return [lim - timedelta(days=n) for n in range(ate, -1, -1)
            if prazos.decidir(data_limite, prazo_dias, lim - timedelta(days=n)).avisar]


def _em(data_limite, prazo_dias, dia, **kw):
    return prazos.decidir(data_limite, prazo_dias, dia, **kw)


def test_nenhum_aviso_cai_em_fim_de_semana():
    """A regra central: o Jurídico não trabalha sábado/domingo."""
    for prazo in (5, 10, 15, 20, 30):
        for d in _dias_que_avisam(VENC, prazo):
            assert eh_dia_util(d), f"prazo {prazo} avisaria em {d:%d/%m %a}"


def test_o_dia_do_vencimento_e_sempre_coberto():
    """20/08/2026 é dia útil, então o aviso 'VENCE HOJE' sai na própria data."""
    d = _em(VENC, 20, date(2026, 8, 20))
    assert d.avisar and d.faltam == 0 and not d.vencido


def test_checkpoint_de_fim_de_semana_e_antecipado_para_a_sexta():
    """Prazo 20, intervalo 4: o checkpoint 'faltam 4' cai em domingo 16/08 e é antecipado
    para sexta 14/08 (faltam 6) — preservando 2 dias de prazo em vez de perdê-los."""
    assert _em(VENC, 20, date(2026, 8, 16)).avisar is False    # domingo: nada
    sexta = _em(VENC, 20, date(2026, 8, 14))
    assert sexta.avisar and sexta.faltam == 6 and sexta.antecipado


def test_sempre_existe_uma_ultima_chance_antes_do_vencimento():
    for prazo in (5, 10, 15, 20, 30):
        ultimas = [d for d in _dias_que_avisam(VENC, prazo)
                   if _em(VENC, prazo, d).ultima_chance]
        assert len(ultimas) == 1, f"prazo {prazo}: {len(ultimas)} 'última chance'"
        assert ultimas[0] < de_ddmmaaaa(VENC)   # estritamente antes do vencimento


def test_ultima_chance_nao_e_o_proprio_dia_do_vencimento():
    """No dia do vencimento já é tarde para montar defesa ou pedir dilação."""
    assert _em(VENC, 20, date(2026, 8, 20)).ultima_chance is False
    assert _em(VENC, 20, date(2026, 8, 14)).ultima_chance is True


def test_ultima_chance_quando_o_vencimento_cai_no_domingo():
    """Vencimento 16/08/2026 (domingo): a sexta 14/08 vira o último aviso possível."""
    d = _em("16/08/2026", 20, date(2026, 8, 14))
    assert d.avisar and d.ultima_chance and d.faltam == 2


def test_cadencia_do_prazo_de_5_avisa_todo_dia_util():
    """Vencimento 19/08/2026 (quarta): avisa 14/08 sex, 17/08 seg, 18/08 ter e 19/08 qua —
    o fim de semana 15-16 fica de fora."""
    dias = [d.day for d in _dias_que_avisam("19/08/2026", 5, ate=5)]
    assert dias == [14, 17, 18, 19]


def test_vencido_avisa_todo_dia_util_ate_moverem_o_card():
    from datetime import timedelta
    lim = de_ddmmaaaa(VENC)
    for n in range(1, 8):
        dia = lim + timedelta(days=n)
        d = _em(VENC, 20, dia)
        assert d.vencido
        assert d.avisar is eh_dia_util(dia)    # não incomoda no fim de semana


def test_nao_repete_o_aviso_no_mesmo_dia():
    """O comando pode ser rodado à mão depois do cron."""
    assert _em(VENC, 20, date(2026, 8, 14), ja_avisou_hoje=True).avisar is False
    assert _em(VENC, 20, date(2026, 8, 21), ja_avisou_hoje=True).avisar is False


def test_sem_data_limite_nao_ha_o_que_contar():
    assert prazos.decidir("", 20, date(2026, 8, 1)) is None
    assert prazos.decidir("data ruim", 20, date(2026, 8, 1)) is None


# --- mensagens --------------------------------------------------------------
def test_aviso_normal_diz_quantos_dias_faltam():
    m = prazos.formatar_aviso(LINHA, _em(VENC, 20, date(2026, 8, 12)))
    assert "faltam 8 dia(s)" in m and "Age Telecomunicações S.A" in m
    assert "Ofício 688 (16067648)" in m and "20/08/2026" in m


def test_aviso_de_ultima_chance_fala_em_defesa_ou_dilacao():
    m = prazos.formatar_aviso(LINHA, _em(VENC, 20, date(2026, 8, 14)))
    assert "ÚLTIMA" in m and "dilação de prazo" in m


def test_aviso_no_dia_do_vencimento():
    assert "VENCE HOJE" in prazos.formatar_aviso(LINHA, _em(VENC, 20, date(2026, 8, 20)))


def test_aviso_de_vencido_conta_os_dias():
    assert "VENCIDO há 4 dia(s)" in prazos.formatar_aviso(LINHA, _em(VENC, 20, date(2026, 8, 24)))


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
    for m in (prazos.formatar_aviso(linha, _em(VENC, 20, date(2026, 8, 14))),
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
                                  hoje=date(2026, 8, 14),  # sexta: antecipa o checkpoint do domingo
                                  enviar=enviadas.append, log=lambda *a: None)
    assert r["avisos"] == 1 and r["paradas"] == 0
    assert "ÚLTIMA" in enviadas[0]


def test_dia_sem_cadencia_nao_avisa(tmp_path):
    store = _store_com_prazo(tmp_path)
    enviadas = []
    r = monitor.acompanhar_prazos(store=store, cards=_cards(STATUS_AGUARDANDO),
                                  hoje=date(2026, 8, 13),  # quinta: fora da cadência
                                  enviar=enviadas.append, log=lambda *a: None)
    assert r["avisos"] == 0 and enviadas == []


def test_saiu_da_raia_para_de_contar_e_avisa_uma_vez(tmp_path):
    """Exigência do usuário: consulta o quadro ANTES de avisar. Se saiu, a mensagem é a
    de parada — nunca mais um lembrete de prazo."""
    store = _store_com_prazo(tmp_path)
    enviadas = []
    hoje = date(2026, 8, 14)   # seria dia de aviso, mas o card saiu da raia
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
    r = monitor.acompanhar_prazos(store=store, cards={}, hoje=date(2026, 8, 14),
                                  enviar=enviadas.append, log=lambda *a: None)
    assert r["sem_card"] == 1
    assert "sem card" in enviadas[0].lower()
    assert store.em_acompanhamento() == []


def test_nao_repete_aviso_se_rodar_duas_vezes_no_mesmo_dia(tmp_path):
    store = _store_com_prazo(tmp_path)
    enviadas = []
    args = dict(store=store, cards=_cards(STATUS_AGUARDANDO), hoje=date(2026, 8, 14),
                log=lambda *a: None)
    monitor.acompanhar_prazos(enviar=enviadas.append, **args)
    monitor.acompanhar_prazos(enviar=enviadas.append, **args)
    assert len(enviadas) == 1


def test_sem_prazo_nao_entra_no_acompanhamento(tmp_path):
    """Intimação de 'mero Conhecimento' não tem prazo de resposta."""
    store = _store_com_prazo(tmp_path, data_limite="", prazo_dias=None)
    assert store.em_acompanhamento() == []


# ---------------------------------------------------------------------------
# Ofício COLETIVO (Fase 4): N empresas, UM aviso (decisão do usuário, 2026-08-10)
# ---------------------------------------------------------------------------
PROC_COL, DOC_COL = "53500.069114/2026-47", "16075320"


def _store_coletivo(tmp_path, empresas=3, data_limite="20/08/2026", prazo_dias=5):
    """Um coletivo vira N linhas em `tratadas` — uma por empresa, mesmo (processo, doc_id)."""
    store = IntimacoesStore(str(tmp_path / "col.db"))
    for n in range(empresas):
        cnpj = f"{n:014d}"
        intim = Intimacao(
            processo=PROC_COL, doc_id=DOC_COL, oficio_desc="Ofício 693",
            destinatario=f"Empresa {n}", documento=cnpj, documento_fmt=cnpj,
            tipo_destinatario="Pessoa Jurídica",
            tipo_intimacao="Comunica Decisão Judicial de Cumprimento - URGENTE",
            data_expedicao="07/08/2026", situacao="Pendente")
        store.marcar_tratado(intim, data_limite, prazo_dias=prazo_dias, prazo_unidade="dias",
                             oficio_desc="Ofício 693", grupo_tipo="coletivo",
                             pasta_url="https://sharepoint/of?a=1&b=2")
    return store


def _cards_col(status):
    return {(PROC_COL, DOC_COL): {"Title": PROC_COL, "StatusOficio": status}}


def test_coletivo_manda_um_aviso_so_para_o_oficio_inteiro(tmp_path):
    store = _store_coletivo(tmp_path)
    enviadas = []
    r = monitor.acompanhar_prazos(store=store, cards=_cards_col(STATUS_AGUARDANDO),
                                  hoje=date(2026, 8, 19),  # prazo 5 dias → avisa todo dia
                                  enviar=enviadas.append, log=lambda *a: None)
    assert r["acompanhando"] == 1 and r["avisos"] == 1
    assert len(enviadas) == 1
    assert "Empresas:</b> 3 (ofício coletivo)" in enviadas[0]
    assert "Empresa:" not in enviadas[0]
    # o link da pasta é o item acionável e não pode ser escapado
    assert '<a href="https://sharepoint/of?a=1&b=2">' in enviadas[0]


def test_coletivo_marca_o_aviso_em_todas_as_empresas(tmp_path):
    """Se só a linha representativa fosse marcada, as outras N-1 voltariam amanhã."""
    store = _store_coletivo(tmp_path)
    enviadas = []
    args = dict(store=store, cards=_cards_col(STATUS_AGUARDANDO), hoje=date(2026, 8, 19),
                log=lambda *a: None)
    monitor.acompanhar_prazos(enviar=enviadas.append, **args)
    monitor.acompanhar_prazos(enviar=enviadas.append, **args)
    assert len(enviadas) == 1
    assert all(l["acomp_ultimo_aviso"] == "2026-08-19" for l in store.em_acompanhamento())


def test_coletivo_para_todas_as_empresas_ao_sair_da_raia(tmp_path):
    store = _store_coletivo(tmp_path)
    enviadas = []
    r = monitor.acompanhar_prazos(store=store, cards=_cards_col("Processo concluído"),
                                  hoje=date(2026, 8, 19), enviar=enviadas.append,
                                  log=lambda *a: None)
    assert r["paradas"] == 1 and len(enviadas) == 1
    assert store.em_acompanhamento() == []


def test_coletivos_diferentes_nao_se_misturam(tmp_path):
    store = _store_coletivo(tmp_path, empresas=2)
    outro = Intimacao(
        processo="53500.000001/2026-11", doc_id="16075999", oficio_desc="Ofício 697",
        destinatario="Outra", documento="99", documento_fmt="99",
        tipo_destinatario="Pessoa Jurídica", tipo_intimacao="Comunica Decisão - URGENTE",
        data_expedicao="07/08/2026", situacao="Pendente")
    store.marcar_tratado(outro, "20/08/2026", prazo_dias=5, prazo_unidade="dias",
                         oficio_desc="Ofício 697", grupo_tipo="coletivo")
    cards = dict(_cards_col(STATUS_AGUARDANDO))
    cards[(outro.processo, outro.doc_id)] = {"Title": outro.processo,
                                             "StatusOficio": STATUS_AGUARDANDO}
    enviadas = []
    r = monitor.acompanhar_prazos(store=store, cards=cards, hoje=date(2026, 8, 19),
                                  enviar=enviadas.append, log=lambda *a: None)
    assert r["acompanhando"] == 2 and len(enviadas) == 2
