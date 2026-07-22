"""Testes do card do ofício (lista ControleOficioJuridico) — builder puro + idempotência."""
from datetime import date

from seibot import oficio_card
from seibot.clientes import ClienteInfo
from seibot.models import Grupo, Intimacao
from seibot.processo import Prazo


def _grupo(processo="53500.064050/2024-26", oficio="Ofício 407", doc_id="15843941",
           tipo_intimacao="Requerimento de Informações"):
    intim = Intimacao(
        processo=processo, doc_id=doc_id, oficio_desc=oficio,
        destinatario="SITELBRA SISTEMA DE TELECOMUNICACOES DO BRASIL LTDA",
        documento="12345678000199", documento_fmt="12.345.678/0001-99",
        tipo_destinatario="Pessoa Jurídica", tipo_intimacao=tipo_intimacao,
        data_expedicao="21/07/2026", situacao="Cumprida por Consulta Direta")
    g = Grupo(processo=processo, doc_id=doc_id, oficio_desc=oficio,
              tipo_intimacao=tipo_intimacao, data_expedicao="21/07/2026",
              situacao="Cumprida por Consulta Direta", destinatarios=(intim,))
    return g, intim


def test_montar_campos_preenche_factuais_e_deixa_workflow_de_fora():
    g, intim = _grupo()
    info = ClienteInfo(cnpj="12345678000199", em_base=True, sp_item_id="3539",
                       emails=("a@x.com", "b@x.com"), telefones=("(11) 1234", "(11) 5678"),
                       pacote="LIGHT")
    prazo = Prazo(tipo="Resposta a Requerimento de Informações", dias=15, data_limite="04/08/2026")
    campos = oficio_card.montar_campos(g, intim, prazo, info, data_cumprimento=date(2026, 7, 22))

    assert campos["Title"] == "53500.064050/2024-26"
    assert campos["NumeroOficio"] == "Ofício 407 (15843941)"
    assert campos["CNPJsemFormatacao"] == "12345678000199"
    assert campos["CNPJLookupId"] == "3539"
    assert campos["DataCumprimento"] == "2026-07-22T03:00:00Z"
    assert campos["DataVencimento"] == "2026-08-04T03:00:00Z"
    assert campos["Email"] == "a@x.com,b@x.com"
    assert campos["Telefone"] == "(11) 1234 / (11) 5678"
    assert campos["Prioridade"] == "Média"     # não-urgente (single choice → string)
    assert campos["Pacote"] == ["LIGHT"]        # multi-choice → lista
    assert campos["Pacote@odata.type"] == "Collection(Edm.String)"  # exigido pelo Graph
    # Status e Tipo de Ofício (workflow), Login/Senha e AGU ficam para o Jurídico
    for k in ("StatusOficio", "TipoOficio", "LoginSEI", "SenhaSEI",
              "PrazoAGUdias", "DataInicioAGU", "DataAGUfim"):
        assert k not in campos


def test_prioridade_alta_quando_urgente_e_pacote_so_com_info():
    g, intim = _grupo(tipo_intimacao="Comunica Decisão Judicial de Cumprimento - URGENTE")
    campos = oficio_card.montar_campos(g, intim, None, None, data_cumprimento=date(2026, 7, 22))
    assert campos["Prioridade"] == "Alta"       # URGENTE → Alta
    assert "Pacote" not in campos               # sem info → sem pacote


def test_montar_campos_sem_prazo_e_sem_info_nao_grava_vazio():
    g, intim = _grupo()
    campos = oficio_card.montar_campos(g, intim, None, None, data_cumprimento=date(2026, 7, 22))
    assert "DataVencimento" not in campos       # sem prazo → sem vencimento
    assert "CNPJLookupId" not in campos          # sem info → sem lookup
    assert "Email" not in campos and "Telefone" not in campos
    assert campos["Title"] and campos["CNPJsemFormatacao"] == "12345678000199"


def test_iso_de_ddmmaaaa():
    assert oficio_card._iso_de_ddmmaaaa("04/08/2026") == "2026-08-04T03:00:00Z"
    assert oficio_card._iso_de_ddmmaaaa("") is None
    assert oficio_card._iso_de_ddmmaaaa("data ruim") is None


class _FakeGraph:
    def __init__(self, existente=None):
        self._existente = existente
        self.criados = []

    def buscar_item(self, lista, title):
        return self._existente

    def criar_item(self, lista, fields):
        self.criados.append((lista, fields))
        return {"id": "999"}


def test_criar_card_cria_quando_nao_existe():
    g, intim = _grupo()
    prazo = Prazo(tipo="X", dias=15, data_limite="04/08/2026")
    info = ClienteInfo(cnpj="12345678000199", em_base=True, sp_item_id="3539", emails=("a@x.com",))
    fake = _FakeGraph(existente=None)
    cid = oficio_card.criar_card(fake, g, intim, prazo, info,
                                 data_cumprimento=date(2026, 7, 22), log=lambda *_: None)
    assert cid == "999"
    assert len(fake.criados) == 1
    lista, fields = fake.criados[0]
    assert lista == oficio_card.LISTA_CONTROLE_OFICIO
    assert fields["Title"] == "53500.064050/2024-26"


def test_criar_card_nao_duplica_quando_ja_existe():
    """Idempotência por Nº do Processo — re-rodar (ex.: --modo completo) não cria card duplicado."""
    g, intim = _grupo()
    fake = _FakeGraph(existente={"id": "42"})
    cid = oficio_card.criar_card(fake, g, intim, None, None, log=lambda *_: None)
    assert cid is None
    assert fake.criados == []
