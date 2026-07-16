"""Testes da seleção de candidatos à tratativa (Fase 2)."""
from seibot.classificar import agrupar_por_oficio
from seibot.clientes import ClienteInfo
from seibot.models import Intimacao
from seibot.tratativa import selecionar_candidatos


def _intim(doc_id, cnpj, situacao="Pendente", tipo="Requerimento de Informações"):
    return Intimacao(
        processo="P" + doc_id, doc_id=doc_id, oficio_desc="Ofício " + doc_id,
        destinatario="Empresa " + cnpj, documento=cnpj, documento_fmt=cnpj,
        tipo_destinatario="Pessoa Jurídica", tipo_intimacao=tipo,
        data_expedicao="16/07/2026", situacao=situacao,
    )


class _Clientes:
    def __init__(self, mapa):
        self._mapa = mapa

    def info(self, cnpj):
        return self._mapa.get(cnpj)

    def status(self, cnpj):
        i = self.info(cnpj)
        return None if i is None else ("ativo" if i.ativo else "inativo")

    def emails(self, cnpj):
        return []


def _ativo(cnpj):
    return ClienteInfo(cnpj=cnpj, em_base=True, status_raw="Ativo")


def _inativo(cnpj):
    return ClienteInfo(cnpj=cnpj, em_base=True, status_raw="Cancelado")


def test_individual_ativo_pendente_eh_candidato():
    g = agrupar_por_oficio([_intim("10", "111")])
    cli = _Clientes({"111": _ativo("111")})
    assert len(selecionar_candidatos(g, cli)) == 1


def test_individual_inativo_nao_eh_candidato():
    g = agrupar_por_oficio([_intim("10", "111")])
    cli = _Clientes({"111": _inativo("111")})
    assert selecionar_candidatos(g, cli) == []


def test_individual_ativo_mas_cumprida_nao_eh_candidato():
    g = agrupar_por_oficio([_intim("10", "111", situacao="Cumprida por Consulta Direta")])
    cli = _Clientes({"111": _ativo("111")})
    assert selecionar_candidatos(g, cli) == []


def test_coletivo_nunca_eh_candidato():
    g = agrupar_por_oficio([_intim("10", "111"), _intim("10", "222")])
    cli = _Clientes({"111": _ativo("111"), "222": _ativo("222")})
    assert selecionar_candidatos(g, cli) == []


def test_fora_da_base_nao_eh_candidato():
    g = agrupar_por_oficio([_intim("10", "999")])
    cli = _Clientes({})  # não encontrado
    assert selecionar_candidatos(g, cli) == []


def test_sem_sharepoint_nao_seleciona():
    g = agrupar_por_oficio([_intim("10", "111")])
    assert selecionar_candidatos(g, None) == []
