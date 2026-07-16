"""Testes da lógica de SharePointClientes com um Graph fake (sem rede)."""
from seibot import graph
from seibot.clientes import ATIVO, INATIVO, SharePointClientes


class _FakeGraph:
    """Imita graph.GraphSharePoint.itens() a partir de dicts em memória."""
    def __init__(self, por_lista):
        self._por_lista = por_lista

    def itens(self, lista_id, top=50, **kw):
        for f in self._por_lista.get(lista_id, []):
            yield {"fields": f}


def _sp(clientes_scm, comercial=None, financeiro=None):
    fake = _FakeGraph({
        graph.LISTA_CLIENTES_SCM: clientes_scm,
        graph.LISTA_COMERCIAL: comercial or [],
        graph.LISTA_FINANCEIRO: financeiro or [],
    })
    return SharePointClientes(g=fake, log=lambda *_: None)


def test_ativo_por_status_da_clientes_scm():
    sp = _sp([{"id": "1", "Title": "11.111.111/1111-11", "field_1": "A", "StatusContrato": "Ativo"}])
    assert sp.status("11111111111111") == ATIVO


def test_uniao_ativo_por_contrato_no_comercial_mesmo_com_status_branco():
    # status em branco na Clientes SCM, mas tem contrato Ativo no Comercial → ativo (união)
    sp = _sp(
        clientes_scm=[{"id": "7", "Title": "22.222.222/2222-22", "field_1": "B", "StatusContrato": ""}],
        comercial=[{"CNPJLookupId": "7", "StatusContrato": "Ativo"}],
    )
    info = sp.info("22222222222222")
    assert info.status_raw == "" and info.contrato_ativo is True
    assert sp.status("22222222222222") == ATIVO


def test_inativo_quando_sem_status_e_sem_contrato_ativo():
    sp = _sp(
        clientes_scm=[{"id": "9", "Title": "33.333.333/3333-33", "StatusContrato": "Cancelado"}],
        comercial=[{"CNPJLookupId": "9", "StatusContrato": "Cancelado"}],
    )
    assert sp.status("33333333333333") == INATIVO


def test_fora_da_base_retorna_none():
    sp = _sp([{"id": "1", "Title": "11.111.111/1111-11", "StatusContrato": "Ativo"}])
    assert sp.status("99999999999999") is None
    assert sp.info("99999999999999") is None


def test_adimplencia_inadimplente_prevalece():
    sp = _sp(
        clientes_scm=[{"id": "5", "Title": "44.444.444/4444-44", "StatusContrato": "Ativo"}],
        financeiro=[
            {"CNPJLookupId": "5", "Situacao": "Adimplentes"},
            {"CNPJLookupId": "5", "Situacao": "Inadimplente 2 Parcelas"},
        ],
    )
    info = sp.info("44444444444444")
    assert info.adimplencia == "inadimplente"
    assert "2 Parcelas" in info.adimplencia_detalhe


def test_emails_agregados_de_varias_colunas():
    sp = _sp([{
        "id": "1", "Title": "11.111.111/1111-11", "StatusContrato": "Ativo",
        "field_3": "a@x.com, b@x.com", "EmailFinanceiro": "b@x.com,c@x.com",
    }])
    emails = sp.emails("11111111111111")
    assert emails == ["a@x.com", "b@x.com", "c@x.com"]
