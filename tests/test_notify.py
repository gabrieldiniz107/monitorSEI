"""Testes de formatação das mensagens Teams."""
from seibot.classificar import agrupar_por_oficio
from seibot.models import Intimacao
from seibot.notify import formatar_grupo


def _intim(cnpj, nome, tipo="Requerimento de Informações"):
    return Intimacao(
        processo="53500.070572/2026-29", doc_id="15963368", oficio_desc="Ofício 498",
        destinatario=nome, documento=cnpj, documento_fmt=cnpj,
        tipo_destinatario="Pessoa Jurídica", tipo_intimacao=tipo,
        data_expedicao="15/07/2026", situacao="Pendente",
    )


def test_mensagem_individual_contem_campos():
    g = agrupar_por_oficio([_intim("19.402.859/0001-55", "CLICKIP LTDA")])[0]
    msg = formatar_grupo(g)
    assert "individual" in msg
    assert "53500.070572/2026-29" in msg
    assert "15963368" in msg
    assert "CLICKIP LTDA" in msg
    assert "19.402.859/0001-55" in msg


def test_mensagem_coletiva_conta_empresas_e_lista():
    ints = [_intim(f"{n}", f"Empresa {n}") for n in range(3)]
    g = agrupar_por_oficio(ints)[0]
    msg = formatar_grupo(g)
    assert "coletivo — 3 empresas" in msg
    assert "Empresa 0" in msg and "Empresa 2" in msg


def test_urgente_marca_titulo_e_tipo():
    g = agrupar_por_oficio([_intim("111", "X", tipo="Comunica Decisão Judicial de Cumprimento - URGENTE")])[0]
    msg = formatar_grupo(g)
    assert msg.startswith("🔴")
    assert "URGENTE" in msg


from seibot.clientes import ClienteInfo


class _ClientesFake:
    def __init__(self, mapa):
        self._mapa = mapa  # cnpj(dig) -> ClienteInfo | None

    def info(self, cnpj):
        import re
        return self._mapa.get(re.sub(r"\D", "", cnpj))

    def status(self, cnpj):
        info = self.info(cnpj)
        return None if info is None else ("ativo" if info.ativo else "inativo")

    def emails(self, cnpj):
        return []


def test_anotacao_status_sharepoint():
    ints = [_intim("111", "Ativa"), _intim("222", "Inativa"), _intim("333", "Fora")]
    g = agrupar_por_oficio(ints)[0]
    clientes = _ClientesFake({
        "111": ClienteInfo(cnpj="111", em_base=True, status_raw="Ativo"),
        "222": ClienteInfo(cnpj="222", em_base=True, status_raw="Cancelado",
                           adimplencia="inadimplente", adimplencia_detalhe="Inadimplente 2 Parcelas"),
        # "333" não está no mapa → fora da base
    })
    msg = formatar_grupo(g, clientes)
    assert "✅ ativo" in msg
    assert "não-ativo (Cancelado)" in msg
    assert "inadimplente" in msg
    assert "fora da base" in msg
    # coletivo: destaca quantas não-ativas (222 inativa + 333 fora da base = 2 de 3)
    assert "2 de 3" in msg


def test_individual_ativo_segue_tratativa():
    g = agrupar_por_oficio([_intim("111", "Ativa")])[0]
    clientes = _ClientesFake({"111": ClienteInfo(cnpj="111", em_base=True, status_raw="Ativo")})
    msg = formatar_grupo(g, clientes)
    assert "Cliente ATIVO" in msg
    assert "tratativa individual" in msg


def test_individual_nao_ativo_so_ciencia_com_motivo():
    g = agrupar_por_oficio([_intim("222", "Cancelada")])[0]
    clientes = _ClientesFake({"222": ClienteInfo(cnpj="222", em_base=True, status_raw="Cancelado")})
    msg = formatar_grupo(g, clientes)
    assert "Sem tratativa automática" in msg
    assert "não-ativo (Cancelado)" in msg


def test_individual_fora_da_base_motivo():
    g = agrupar_por_oficio([_intim("999", "Desconhecida")])[0]
    clientes = _ClientesFake({})  # não encontrado
    msg = formatar_grupo(g, clientes)
    assert "Sem tratativa automática" in msg
    assert "fora da base" in msg


def test_html_usa_br_e_negrito_sem_quebra_de_linha_crua():
    from seibot.notify import formatar_grupo_html
    ints = [_intim("111", "Empresa & Cia"), _intim("222", "Outra")]
    g = agrupar_por_oficio(ints)[0]
    html = formatar_grupo_html(g)
    assert "<br>" in html          # quebras de linha via HTML
    assert "<b>Processo:</b>" in html
    assert "\n" not in html        # nada de newline cru (viraria "texto corrido")
    assert "&amp;" in html         # "&" da razão social escapado


def test_html_individual_tem_decisao_em_negrito():
    from seibot.notify import formatar_grupo_html
    g = agrupar_por_oficio([_intim("111", "Ativa")])[0]
    clientes = _ClientesFake({"111": ClienteInfo(cnpj="111", em_base=True, status_raw="Ativo")})
    html = formatar_grupo_html(g, clientes)
    assert "Cliente ATIVO" in html and "<b>" in html
