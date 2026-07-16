"""Testes do parser puro (parse_pagina) — fixture real + casos sintéticos.

A fixture real (`intimacoes_page.html`) tem dados de clientes reais e NÃO é versionada
(está no .gitignore). Os testes que dependem dela são pulados quando o arquivo não existe
(ex.: num clone limpo/CI); os casos sintéticos abaixo sempre rodam.
"""
from pathlib import Path

import pytest

from seibot.intimacoes import ler_total, parse_pagina

FIXTURE = Path(__file__).parent / "fixtures" / "intimacoes_page.html"
_sem_fixture = pytest.mark.skipif(not FIXTURE.exists(),
                                  reason="fixture real ausente (dados reais, não versionada)")


@_sem_fixture
def test_parse_fixture_real_conta_linhas():
    html = FIXTURE.read_text(encoding="utf-8")
    ints = parse_pagina(html)
    assert len(ints) == 100
    assert ler_total(html) == 9443


@_sem_fixture
def test_parse_fixture_extrai_campos_de_uma_linha_conhecida():
    html = FIXTURE.read_text(encoding="utf-8")
    ints = parse_pagina(html)
    alvo = next(i for i in ints if i.processo == "53500.070572/2026-29")
    assert alvo.doc_id == "15963368"
    assert alvo.oficio_desc == "Ofício 498"
    assert alvo.destinatario == "CLICKIP SERVICOS DE COMUNICACAO LTDA"
    assert alvo.documento == "19402859000155"
    assert alvo.documento_fmt == "19.402.859/0001-55"
    assert alvo.tipo_destinatario == "Pessoa Jurídica"
    assert alvo.situacao == "Pendente"
    assert alvo.prioridade_urgente is False
    assert alvo.chave == "53500.070572/2026-29|15963368|19402859000155"


def test_parse_pagina_vazia_retorna_lista_vazia():
    assert parse_pagina("<html><body>sem tabela</body></html>") == []


# --- casos sintéticos: PF (CPF) e prioridade URGENTE ---
_LINHA_PF_URGENTE = """
<table summary="Intimações Eletrônicas">
<tr><th>cabeçalho</th></tr>
<tr data-idintimacao="99" data-docprinc="12345" data-doctipo="Ofício 1 ">
  <td data-label="Processo"><a>53500.000001/2026-01</a></td>
  <td data-label="Data de Expedição">14/07/2026</td>
  <td data-label="Documento Principal">Ofício 1 (12345)</td>
  <td data-label="Destinatário">João da Silva (123.456.789-09)</td>
  <td data-label="Tipo de Destinatário">Pessoa Física</td>
  <td data-label="Tipo de Intimação">Comunica Decisão Judicial de Cumprimento - URGENTE</td>
  <td data-label="Situação">Pendente</td>
  <td data-label="Ações"><a onclick="window.open('...')"><img></a></td>
</tr>
</table>
"""


def test_parse_pessoa_fisica_com_cpf_e_urgente():
    ints = parse_pagina(_LINHA_PF_URGENTE)
    assert len(ints) == 1
    i = ints[0]
    assert i.tipo_destinatario == "Pessoa Física"
    assert i.destinatario == "João da Silva"
    assert i.documento == "12345678909"
    assert i.documento_fmt == "123.456.789-09"
    assert i.prioridade_urgente is True
