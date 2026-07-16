"""Testes de classificação coletivo vs individual."""
from seibot.classificar import agrupar_por_oficio
from seibot.models import Intimacao


def _intim(processo, doc_id, cnpj, nome="Empresa X", tipo="Requerimento de Informações"):
    return Intimacao(
        processo=processo, doc_id=doc_id, oficio_desc=f"Ofício {doc_id}",
        destinatario=nome, documento=cnpj, documento_fmt=cnpj,
        tipo_destinatario="Pessoa Jurídica", tipo_intimacao=tipo,
        data_expedicao="14/07/2026", situacao="Pendente",
    )


def test_mesmo_oficio_varias_empresas_eh_coletivo():
    ints = [
        _intim("P1", "10", "111"),
        _intim("P1", "10", "222"),
        _intim("P1", "10", "333"),
    ]
    grupos = agrupar_por_oficio(ints)
    assert len(grupos) == 1
    assert grupos[0].tipo == "coletivo"
    assert len(grupos[0].destinatarios) == 3


def test_oficio_unico_destinatario_eh_individual():
    grupos = agrupar_por_oficio([_intim("P2", "20", "444")])
    assert len(grupos) == 1
    assert grupos[0].tipo == "individual"


def test_oficios_diferentes_geram_grupos_separados():
    ints = [_intim("P1", "10", "111"), _intim("P1", "11", "111")]
    grupos = agrupar_por_oficio(ints)
    assert len(grupos) == 2


def test_prioridade_urgente_propaga_para_o_grupo():
    ints = [
        _intim("P1", "10", "111", tipo="Requerimento de Informações"),
        _intim("P1", "10", "222", tipo="Comunica Decisão Administrativa de Cumprimento - URGENTE"),
    ]
    grupos = agrupar_por_oficio(ints)
    assert grupos[0].prioridade_urgente is True
