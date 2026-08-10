"""Testes do dedup SQLite (IntimacoesStore) e do ciclo de vida da tratativa."""
import sqlite3

from seibot.models import Intimacao
from seibot.store import (PROMESSA_ABERTA, PROMESSA_DESCARTADA, PROMESSA_TRATADA,
                          IntimacoesStore)


def _intim(chave_cnpj="111"):
    return Intimacao(
        processo="P1", doc_id="10", oficio_desc="Ofício 10",
        destinatario="Empresa", documento=chave_cnpj, documento_fmt=chave_cnpj,
        tipo_destinatario="Pessoa Jurídica", tipo_intimacao="Requerimento de Informações",
        data_expedicao="14/07/2026", situacao="Pendente",
    )


def test_marcar_e_checar(tmp_path):
    store = IntimacoesStore(str(tmp_path / "t.db"))
    i = _intim()
    assert store.ja_visto(i.chave) is False
    store.marcar_visto(i, "individual")
    assert store.ja_visto(i.chave) is True
    assert store.contar() == 1


def test_idempotente(tmp_path):
    store = IntimacoesStore(str(tmp_path / "t.db"))
    i = _intim()
    store.marcar_visto(i, "individual")
    store.marcar_visto(i, "individual")
    assert store.contar() == 1


def test_marcar_lote_baseline(tmp_path):
    store = IntimacoesStore(str(tmp_path / "t.db"))
    ints = [_intim("111"), _intim("222"), _intim("333")]
    n = store.marcar_lote(ints)
    assert n == 3
    assert store.contar() == 3
    assert all(store.ja_visto(i.chave) for i in ints)


# ---------------------------------------------------------------------------
# tratadas: o prazo NÃO pode se perder (bug de produção, 05/08/2026)
# ---------------------------------------------------------------------------
def test_checkpoint_e_depois_prazo_persiste_a_data(tmp_path):
    """Regressão do bug real: `--modo real` grava o checkpoint (sem prazo) logo após a
    ciência e o prazo só no fim. Com `INSERT OR IGNORE` a segunda gravação sumia — as 12
    linhas do banco de produção estavam todas com data_limite vazio."""
    store = IntimacoesStore(str(tmp_path / "t.db"))
    i = _intim()

    store.marcar_tratado(i, "")                       # checkpoint pós-ciência
    assert store.ja_tratado(i.chave) is True
    assert store.prazo_de(i.chave) == ("", None, "")

    store.marcar_tratado(i, "19/08/2026", prazo_dias=20, prazo_unidade="dias úteis")
    assert store.prazo_de(i.chave) == ("19/08/2026", 20, "dias úteis")


def test_checkpoint_posterior_nao_apaga_prazo_ja_gravado(tmp_path):
    """Ordem inversa (retomada de pipeline): o checkpoint sem prazo não pode zerar o que
    já foi capturado."""
    store = IntimacoesStore(str(tmp_path / "t.db"))
    i = _intim()
    store.marcar_tratado(i, "19/08/2026", prazo_dias=20, prazo_unidade="dias úteis")
    store.marcar_tratado(i, "")
    assert store.prazo_de(i.chave) == ("19/08/2026", 20, "dias úteis")


def test_ja_tratado_continua_travando_ciencia_dupla(tmp_path):
    store = IntimacoesStore(str(tmp_path / "t.db"))
    i = _intim()
    assert store.ja_tratado(i.chave) is False
    store.marcar_tratado(i, "")
    assert store.ja_tratado(i.chave) is True


def test_migra_banco_antigo_sem_as_colunas_de_prazo(tmp_path):
    """O banco de produção é montado por volume e já existe com o schema velho —
    tem que ganhar as colunas por ALTER TABLE, sem perder as linhas."""
    p = str(tmp_path / "velho.db")
    with sqlite3.connect(p) as con:
        con.execute("CREATE TABLE tratadas (chave TEXT PRIMARY KEY, processo TEXT,"
                    " doc_id TEXT, cnpj TEXT, data_limite TEXT, tratado_em TEXT)")
        con.execute("INSERT INTO tratadas (chave, data_limite) VALUES ('P1|10|111', '')")

    store = IntimacoesStore(p)           # __init__ migra
    assert store.prazo_de("P1|10|111") == ("", None, None)
    store.marcar_tratado(_intim(), "19/08/2026", prazo_dias=20, prazo_unidade="dias")
    assert store.prazo_de("P1|10|111") == ("19/08/2026", 20, "dias")


def test_tratada_nasce_individual_e_o_coletivo_se_identifica(tmp_path):
    """`grupo_tipo` é o que permite ao acompanhamento colapsar as N linhas de um coletivo
    num aviso só. Linha antiga/individual não pode virar coletivo por omissão."""
    store = IntimacoesStore(str(tmp_path / "t.db"))
    i = _intim()
    store.marcar_tratado(i, "19/08/2026", prazo_dias=20)
    assert store.em_acompanhamento()[0]["grupo_tipo"] == "individual"

    store.marcar_tratado(i, "19/08/2026", prazo_dias=20, grupo_tipo="coletivo",
                         pasta_url="https://sharepoint/x")
    linha = store.em_acompanhamento()[0]
    assert linha["grupo_tipo"] == "coletivo"
    assert linha["pasta_url"] == "https://sharepoint/x"


def test_checkpoint_do_coletivo_nao_reverte_o_tipo_nem_apaga_a_pasta(tmp_path):
    """O checkpoint pós-ciência chama sem tipo/pasta; retomada de pipeline não pode
    rebaixar a linha para 'individual' (perderia o agrupamento do aviso)."""
    store = IntimacoesStore(str(tmp_path / "t.db"))
    i = _intim()
    store.marcar_tratado(i, "19/08/2026", prazo_dias=5, grupo_tipo="coletivo",
                         pasta_url="https://sharepoint/x")
    store.marcar_tratado(i, "19/08/2026", prazo_dias=5)   # checkpoint/regravação sem os dois
    linha = store.em_acompanhamento()[0]
    assert linha["grupo_tipo"] == "coletivo" and linha["pasta_url"] == "https://sharepoint/x"


# ---------------------------------------------------------------------------
# promessas: reconciliação run → tratar
# ---------------------------------------------------------------------------
def test_promessa_registra_e_lista_aberta(tmp_path):
    store = IntimacoesStore(str(tmp_path / "t.db"))
    i = _intim()
    store.registrar_promessa(i, "Ofício 10")
    (p,) = store.promessas_abertas()
    assert p["chave"] == i.chave and p["estado"] == PROMESSA_ABERTA
    assert p["empresa"] == "Empresa" and p["oficio_desc"] == "Ofício 10"
    assert p["situacao_na_promessa"] == "Pendente"


def test_promessa_quitada_some_das_abertas_e_guarda_o_motivo(tmp_path):
    store = IntimacoesStore(str(tmp_path / "t.db"))
    i = _intim()
    store.registrar_promessa(i, "Ofício 10")
    store.quitar_promessa(i.chave, PROMESSA_DESCARTADA, "cliente INADIMPLENTE", avisada=True)
    assert store.promessas_abertas() == []


def test_registrar_promessa_nao_reabre_uma_ja_quitada(tmp_path):
    """O `run` roda 4x/dia; re-notificar não pode ressuscitar uma promessa já resolvida."""
    store = IntimacoesStore(str(tmp_path / "t.db"))
    i = _intim()
    store.registrar_promessa(i, "Ofício 10")
    store.quitar_promessa(i.chave, PROMESSA_TRATADA)
    store.registrar_promessa(i, "Ofício 10")
    assert store.promessas_abertas() == []


def test_marcar_promessa_avisada_mantem_aberta(tmp_path):
    """Intimação que saiu da janela de raspagem: avisa uma vez, mas segue aberta para
    poder ser tratada se voltar."""
    store = IntimacoesStore(str(tmp_path / "t.db"))
    i = _intim()
    store.registrar_promessa(i, "Ofício 10")
    store.marcar_promessa_avisada(i.chave)
    (p,) = store.promessas_abertas()
    assert p["estado"] == PROMESSA_ABERTA and p["avisada"] == 1
