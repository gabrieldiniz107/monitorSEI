"""Testes dos parsers puros do Increment 3 (anexos + prazo)."""
from seibot.processo import Prazo, extrair_anexos, parse_prazo

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
