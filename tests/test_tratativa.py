"""Testes da seleção de candidatos à tratativa (Fase 2)."""
import pytest

from seibot import processo as processo_mod
from seibot import tratativa
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


# ---------------------------------------------------------------------------
# Salvaguarda: intimação ainda PENDENTE (ícone de aceite presente) + dar_ciencia=False
# ⇒ aborta ANTES de tocar em qualquer coisa. Protege o modo 'ensaio' e o 'completo'.
# ---------------------------------------------------------------------------
class _Sess:
    page = object()
    context = object()


def test_pendente_sem_autorizacao_aborta_sem_dar_ciencia(monkeypatch):
    chamou = []
    monkeypatch.setattr(processo_mod, "abrir_processo", lambda *a, **k: None)
    monkeypatch.setattr(processo_mod, "urls_aceite",
                        lambda page: [{"url": "u", "num": "1", "principal": True}])
    monkeypatch.setattr(processo_mod, "dar_ciencia",
                        lambda *a, **k: chamou.append("ciencia"))

    g = agrupar_por_oficio([_intim("10", "111")])[0]
    with pytest.raises(RuntimeError, match="PENDENTE"):
        tratativa.tratar_um(_Sess(), object(), g, _Clientes({"111": _ativo("111")}),
                            store=None, criar_rascunho=False, dar_ciencia=False, log=lambda *a: None)
    assert chamou == []  # não deu ciência


def test_falha_apos_ciencia_vira_TratativaIncompleta(monkeypatch):
    """Se quebrar DEPOIS da ciência, o erro tem que carregar esse estado (prazo correndo,
    sem retry, cliente não avisado) para virar alerta CRÍTICO."""
    monkeypatch.setattr(processo_mod, "abrir_processo", lambda *a, **k: None)
    monkeypatch.setattr(processo_mod, "urls_aceite",
                        lambda page: [{"url": "u", "num": "1", "principal": True}])
    monkeypatch.setattr(processo_mod, "dar_ciencia", lambda *a, **k: None)
    monkeypatch.setattr(processo_mod, "mapa_protocolos", lambda page: {})  # falha pós-ciência

    class _Store:
        marcou = []

        def marcar_tratado(self, intim, data_limite=""):
            self.marcou.append(intim.chave)

    store = _Store()
    g = agrupar_por_oficio([_intim("10", "111")])[0]
    with pytest.raises(tratativa.TratativaIncompleta) as ei:
        tratativa.tratar_um(_Sess(), object(), g, _Clientes({"111": _ativo("111")}),
                            store, criar_rascunho=False, dar_ciencia=True, log=lambda *a: None)
    assert ei.value.empresa == "Empresa 111"
    assert store.marcou  # checkpoint gravado antes da falha


def test_ja_cumprida_nao_tenta_dar_ciencia(monkeypatch):
    """Sem ícone de aceite (já cumprida) o fluxo segue direto, sem ciência."""
    chamou = []
    monkeypatch.setattr(processo_mod, "abrir_processo", lambda *a, **k: None)
    monkeypatch.setattr(processo_mod, "urls_aceite", lambda page: [])
    monkeypatch.setattr(processo_mod, "dar_ciencia", lambda *a, **k: chamou.append("ciencia"))
    monkeypatch.setattr(processo_mod, "mapa_protocolos", lambda page: {})

    g = agrupar_por_oficio([_intim("10", "111", situacao="Cumprida por Consulta Direta")])[0]
    with pytest.raises(RuntimeError, match="Lista de Protocolos vazia"):
        tratativa.tratar_um(_Sess(), object(), g, _Clientes({"111": _ativo("111")}),
                            store=None, criar_rascunho=False, dar_ciencia=True, log=lambda *a: None)
    assert chamou == []


# --- regra de adimplência (decisão 2026-07-21) -------------------------------------
def _ativo_inadimplente(cnpj, detalhe="Inadimplente 2 Parcelas"):
    return ClienteInfo(cnpj=cnpj, em_base=True, status_raw="Ativo",
                       adimplencia="inadimplente", adimplencia_detalhe=detalhe)


def test_ativo_inadimplente_nao_eh_candidato():
    """Ativo mas inadimplente: o bot NÃO abre nem dá ciência (só avisa o Jurídico)."""
    g = agrupar_por_oficio([_intim("10", "111")])
    cli = _Clientes({"111": _ativo_inadimplente("111")})
    assert selecionar_candidatos(g, cli) == []


def test_ativo_adimplente_explicito_eh_candidato():
    g = agrupar_por_oficio([_intim("10", "111")])
    info = ClienteInfo(cnpj="111", em_base=True, status_raw="Ativo", adimplencia="adimplente")
    assert len(selecionar_candidatos(g, _Clientes({"111": info}))) == 1


def test_ativo_sem_registro_financeiro_eh_candidato():
    """`adimplencia=None` (sem registro no Financeiro, ~18% dos ativos) NÃO bloqueia."""
    g = agrupar_por_oficio([_intim("10", "111")])
    info = ClienteInfo(cnpj="111", em_base=True, status_raw="Ativo", adimplencia=None)
    assert len(selecionar_candidatos(g, _Clientes({"111": info}))) == 1


# --- fiação: os nºs dos ícones de aceite têm que chegar ao filtro de anexos ----------
def test_docs_da_intimacao_capturados_antes_da_ciencia_filtram_os_anexos(monkeypatch):
    """Ponta a ponta com os dados REAIS do proc 53539.000753/2026-51 (21/07/2026).

    Os ícones de aceite (Ofício 268 + Despacho 476) somem depois da ciência, então precisam
    ser capturados ANTES e atravessar até a montagem do e-mail. Se a fiação quebrar, o
    fallback pega a Lista de Protocolos inteira e 'Consulta CNPJ'/'Consulta' — documentos
    internos da Anatel — vão parar no e-mail do cliente.
    """
    protos = {
        "15987435": {"tipo": "Despacho Decisório 476", "url": "u1"},
        "15987480": {"tipo": "Ofício 268", "url": "u2"},
        "15987610": {"tipo": "Consulta CNPJ", "url": "u3"},
        "15987617": {"tipo": "Consulta", "url": "u4"},
        "15990001": {"tipo": "Certidão de Intimação Cumprida", "url": "u5"},
    }
    baixados = []

    monkeypatch.setattr(processo_mod, "abrir_processo", lambda *a, **k: None)
    # antes da ciência: 2 ícones. Depois some (a 2ª chamada nem acontece — é capturado antes)
    monkeypatch.setattr(processo_mod, "urls_aceite", lambda page: [
        {"url": "u", "num": "15987435", "principal": False},
        {"url": "u", "num": "15987480", "principal": True},
    ])
    monkeypatch.setattr(processo_mod, "dar_ciencia", lambda *a, **k: None)
    monkeypatch.setattr(processo_mod, "mapa_protocolos", lambda page: protos)
    monkeypatch.setattr(processo_mod, "url_peticionar_resposta", lambda page: None)
    monkeypatch.setattr(processo_mod, "oficio_pdf", lambda page, url: b"%PDF-fake")
    monkeypatch.setattr(processo_mod, "baixar",
                        lambda ctx, url: baixados.append(url) or b"<html>oficio</html>")
    monkeypatch.setattr("seibot.resumo.resumir", lambda *a, **k: "resumo")

    enviados = {}

    class _Store:
        def marcar_tratado(self, intim, data_limite=""):
            pass

    g = agrupar_por_oficio([_intim("15987480", "111")])[0]
    monkeypatch.setattr("seibot.rascunho.montar_mensagem_graph",
                        lambda emails, assunto, corpo, anexos: enviados.setdefault("anexos", anexos))

    r = tratativa.tratar_um(_Sess(), object(), g, _Clientes({"111": _ativo("111")}),
                            _Store(), criar_rascunho=False, dar_ciencia=True, log=lambda *a: None)

    assert r["anexos"] == 1                      # só o Despacho — não os 4 do processo
    nomes = [n for n, _ in enviados["anexos"]]
    assert any("Despacho" in n for n in nomes)
    assert not any("Consulta" in n or "Certid" in n for n in nomes)
