"""Testes dos parsers puros do Increment 3 (anexos + prazo)."""
from seibot.processo import Prazo, anexos_de_protocolos, extrair_anexos, parse_prazo

# Lista de Protocolos REAL do proc 53508.003179/2026-50 (após a ciência, 2026-07-20)
_PROTOCOLOS = {
    "15981049": {"tipo": "Requerimento de Informações", "url": "u1"},
    "15981037": {"tipo": "Planilha de Avaliação de Maturidade Cibernética", "url": "u2"},
    "15981104": {"tipo": "Ofício 70", "url": "u3"},
    "15988916": {"tipo": "Certidão de Intimação Cumprida", "url": "u4"},
}


def test_anexos_excluem_oficio_e_certidao():
    assert anexos_de_protocolos(_PROTOCOLOS, "15981104") == ["15981049", "15981037"]


def test_anexos_nao_dependem_do_texto_do_oficio():
    """O Ofício 70 citava só 1 dos 2 anexos — a Lista de Protocolos manda."""
    assert anexos_de_protocolos(_PROTOCOLOS, "15981104", ["15981037"]) == \
        ["15981037", "15981049"]


def test_anexos_citados_apenas_reordenam():
    r = anexos_de_protocolos(_PROTOCOLOS, "15981104", ["15981049"])
    assert r[0] == "15981049" and sorted(r) == ["15981037", "15981049"]


def test_processo_so_com_oficio_nao_tem_anexos():
    assert anexos_de_protocolos({"15981104": {"tipo": "Ofício 70"}}, "15981104") == []

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
