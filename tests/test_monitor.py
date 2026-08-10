"""Testes do orquestrador executar() com fakes (coletar/enviar) + store real em tmp_path."""
from dataclasses import replace

import pytest

from seibot import monitor
from seibot.config import Config
from seibot.models import Intimacao
from seibot.store import IntimacoesStore


def _cfg(**over):
    """Config de teste com TODO canal de saída em branco.

    `Config` avalia `os.getenv(...)` nos defaults de campo (no import, logo após o
    `load_dotenv`), então um `Config()` nu dentro do teste É a config de produção. Sem
    zerar isto aqui, `test_erro_ao_enviar_nao_marca_e_reenvia` faz `monitor.executar`
    chamar `erros.notificar_erro` → DM REAL no Teams do responsável técnico (aconteceu
    em 05/08/2026: dois alertas "ofício 10/20 · P10/P20" saíram de uma rodada de pytest).
    """
    egresso = dict(teams_dev_email="", teams_webhook_erros_url="", teams_webhook_url="",
                   powerautomate_rascunho_url="")
    return replace(Config(), **{**egresso, **over})


def _intim(doc_id, cnpj, tipo="Requerimento de Informações"):
    return Intimacao(
        processo="P" + doc_id, doc_id=doc_id, oficio_desc="Ofício " + doc_id,
        destinatario="Empresa " + cnpj, documento=cnpj, documento_fmt=cnpj,
        tipo_destinatario="Pessoa Jurídica", tipo_intimacao=tipo,
        data_expedicao="14/07/2026", situacao="Pendente",
    )


def _fake_coletar(intims):
    def _c(page, cfg, **kw):
        return list(intims)
    return _c


# um ofício coletivo (2 empresas) + um individual = 2 grupos, 3 intimações
INTIMS = [_intim("10", "111"), _intim("10", "222"), _intim("20", "333")]


def test_notifica_e_marca_e_eh_idempotente(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor.intimacoes, "coletar", _fake_coletar(INTIMS))
    store = IntimacoesStore(str(tmp_path / "t.db"))
    enviados = []
    cfg = _cfg(seed_max=50)

    res = monitor.executar(cfg, page=None, store=store, enviar=enviados.append)
    assert res["status"] == "ok"
    assert res["novos"] == 2 and res["notificados"] == 2
    assert len(enviados) == 2
    assert store.contar() == 3  # 3 intimações marcadas

    # segunda execução: nada novo
    res2 = monitor.executar(cfg, page=None, store=store, enviar=enviados.append)
    assert res2["novos"] == 0 and res2["notificados"] == 0
    assert len(enviados) == 2


def test_erro_ao_enviar_nao_marca_e_reenvia(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor.intimacoes, "coletar", _fake_coletar(INTIMS))
    store = IntimacoesStore(str(tmp_path / "t.db"))
    cfg = _cfg(seed_max=50)

    def quebra(_g):
        raise RuntimeError("webhook fora")

    res = monitor.executar(cfg, page=None, store=store, enviar=quebra)
    assert res["status"] == "parcial"
    assert res["falhas"] == 2 and res["notificados"] == 0
    assert store.contar() == 0  # nada marcado

    # agora com envio ok → reenvia tudo
    enviados = []
    res2 = monitor.executar(cfg, page=None, store=store, enviar=enviados.append)
    assert res2["notificados"] == 2
    assert store.contar() == 3


def test_guarda_anti_massa_com_banco_vazio(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor.intimacoes, "coletar", _fake_coletar(INTIMS))
    store = IntimacoesStore(str(tmp_path / "t.db"))
    cfg = _cfg(seed_max=1)  # 2 grupos novos > teto 1

    enviados = []
    res = monitor.executar(cfg, page=None, store=store, enviar=enviados.append)
    assert res["status"] == "abortado_seed"
    assert enviados == []
    assert store.contar() == 0


# ---------------------------------------------------------------------------
# Promessa de tratativa: o `run` registra o que prometeu ao Jurídico
# ---------------------------------------------------------------------------
from seibot.clientes import ClienteInfo
from seibot.store import PROMESSA_ABERTA


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


def _inadimplente(cnpj):
    return ClienteInfo(cnpj=cnpj, em_base=True, status_raw="Ativo",
                       adimplencia="inadimplente", adimplencia_detalhe="Inadimplente 2 Parcelas")


def test_run_registra_promessa_so_para_individual_tratavel(tmp_path, monkeypatch):
    """Mesma condição que `notify._decisao_individual` usa para prometer no Teams.
    INTIMS = ofício 10 coletivo (111+222) + ofício 20 individual (333)."""
    monkeypatch.setattr(monitor.intimacoes, "coletar", _fake_coletar(INTIMS))
    store = IntimacoesStore(str(tmp_path / "t.db"))
    cli = _Clientes({"111": _ativo("111"), "222": _ativo("222"), "333": _ativo("333")})

    res = monitor.executar(_cfg(), page=None, store=store, enviar=lambda g: None,
                           clientes=cli, log=lambda *a: None)
    assert res["prometidos"] == 1                      # só o individual
    (p,) = store.promessas_abertas()
    assert p["doc_id"] == "20" and p["estado"] == PROMESSA_ABERTA


def test_run_nao_promete_individual_inadimplente(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor.intimacoes, "coletar", _fake_coletar(INTIMS))
    store = IntimacoesStore(str(tmp_path / "t.db"))
    cli = _Clientes({"111": _ativo("111"), "222": _ativo("222"), "333": _inadimplente("333")})

    res = monitor.executar(_cfg(), page=None, store=store, enviar=lambda g: None,
                           clientes=cli, log=lambda *a: None)
    assert res["prometidos"] == 0 and store.promessas_abertas() == []


def test_run_sem_sharepoint_nao_promete(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor.intimacoes, "coletar", _fake_coletar(INTIMS))
    store = IntimacoesStore(str(tmp_path / "t.db"))
    res = monitor.executar(_cfg(), page=None, store=store, enviar=lambda g: None,
                           clientes=None, log=lambda *a: None)
    assert res["prometidos"] == 0


def test_promessa_so_depois_do_envio_bem_sucedido(tmp_path, monkeypatch):
    """Se o Teams não recebeu, não houve promessa — senão o `tratar` cobraria uma
    tratativa que o Jurídico nunca viu prometida."""
    monkeypatch.setattr(monitor.intimacoes, "coletar", _fake_coletar(INTIMS))
    store = IntimacoesStore(str(tmp_path / "t.db"))
    cli = _Clientes({"111": _ativo("111"), "222": _ativo("222"), "333": _ativo("333")})

    def quebra(_g):
        raise RuntimeError("webhook fora")

    res = monitor.executar(_cfg(), page=None, store=store, enviar=quebra,
                           clientes=cli, log=lambda *a: None)
    assert res["prometidos"] == 0 and store.promessas_abertas() == []


# ---------------------------------------------------------------------------
# Reconciliação: nenhuma promessa termina a execução sem destino
# ---------------------------------------------------------------------------
def _captura_teams(monkeypatch) -> list:
    """`_reconciliar_promessas` importa `enviar_teams_webhook` de dentro da função,
    então o patch no atributo do módulo pega."""
    enviadas = []
    import seibot.teams as teams_mod
    monkeypatch.setattr(teams_mod, "enviar_teams_webhook",
                        lambda url, msg, style="text", **k: enviadas.append(msg))
    return enviadas


def test_reconciliar_quita_promessa_tratada(tmp_path, monkeypatch):
    store = IntimacoesStore(str(tmp_path / "t.db"))
    intim = _intim("20", "333")
    store.registrar_promessa(intim, "Ofício 20")
    grupos = monitor.classificar.agrupar_por_oficio([intim])

    monitor._reconciliar_promessas(_cfg(), store, grupos, _Clientes({"333": _ativo("333")}),
                                   {intim.chave}, log=lambda *a: None)
    assert store.promessas_abertas() == []


def test_reconciliar_avisa_o_grupo_quando_a_situacao_mudou(tmp_path, monkeypatch):
    """O caso da Age Telecomunicações: prometida às 07:00, deixou de ser candidata às
    07:10, e antes disso ninguém ficava sabendo."""
    store = IntimacoesStore(str(tmp_path / "t.db"))
    prometida = _intim("20", "333")
    store.registrar_promessa(prometida, "Ofício 20")
    # na raspagem do `tratar` ela aparece já Respondida
    agora = replace(prometida, situacao="Respondida")
    grupos = monitor.classificar.agrupar_por_oficio([agora])

    enviadas = _captura_teams(monkeypatch)
    n = monitor._reconciliar_promessas(_cfg(teams_webhook_url="https://webhook"), store,
                                       grupos, _Clientes({"333": _ativo("333")}),
                                       set(), log=lambda *a: None)
    assert n == 1
    assert "NÃO executada" in enviadas[0] and "Respondida" in enviadas[0]
    assert store.promessas_abertas() == []   # quitada como descartada


def test_reconciliar_avisa_uma_vez_quando_saiu_da_janela(tmp_path, monkeypatch):
    """Sumiu da raspagem: avisa, mas mantém aberta (pode voltar) e não repete o aviso."""
    store = IntimacoesStore(str(tmp_path / "t.db"))
    store.registrar_promessa(_intim("20", "333"), "Ofício 20")

    enviadas = _captura_teams(monkeypatch)
    cfg = _cfg(teams_webhook_url="https://webhook")

    assert monitor._reconciliar_promessas(cfg, store, [], _Clientes({}), set(),
                                          log=lambda *a: None) == 1
    assert "saiu da janela" in enviadas[0]
    assert len(store.promessas_abertas()) == 1           # segue aberta

    assert monitor._reconciliar_promessas(cfg, store, [], _Clientes({}), set(),
                                          log=lambda *a: None) == 0
    assert len(enviadas) == 1                            # não repetiu


def test_reconciliar_nao_avisa_quando_ainda_eh_candidata(tmp_path, monkeypatch):
    """Ainda candidata = falhou na tratativa; isso já vira DM técnica. Não duplicar no grupo."""
    store = IntimacoesStore(str(tmp_path / "t.db"))
    intim = _intim("20", "333")
    store.registrar_promessa(intim, "Ofício 20")
    grupos = monitor.classificar.agrupar_por_oficio([intim])

    enviadas = _captura_teams(monkeypatch)
    n = monitor._reconciliar_promessas(_cfg(teams_webhook_url="https://webhook"), store,
                                       grupos, _Clientes({"333": _ativo("333")}),
                                       set(), log=lambda *a: None)
    assert n == 0 and enviadas == []
    assert len(store.promessas_abertas()) == 1


# --------------------------------------------------------- fim de semana: automação off
# Decisão do usuário (2026-08-10): "a automação, no geral, roda só durante a semana".
# `tratar`/`coletivo --modo real` já paravam por causa da ciência; agora vale para todos os
# comandos que o cron dispara.
def test_run_e_prazos_param_no_fim_de_semana():
    from datetime import date

    sabado, domingo = date(2026, 8, 15), date(2026, 8, 16)
    for comando in ("run", "prazos"):
        for dia in (sabado, domingo):
            r = monitor._pular_fim_de_semana(comando, dia)
            assert r is not None and "fim de semana" in r["pulado"]


def test_em_dia_util_a_automacao_segue():
    from datetime import date

    for comando in ("run", "prazos"):
        assert monitor._pular_fim_de_semana(comando, date(2026, 8, 14)) is None   # sexta


def test_comandos_de_operacao_rodam_em_qualquer_dia():
    """dry-run/baseline são ferramentas de quem está ao teclado — não podem ser bloqueados
    no sábado só porque o cron não roda nesse dia."""
    from datetime import date

    sabado = date(2026, 8, 15)
    for comando in ("dry-run", "baseline", "tratar", "coletivo"):
        assert monitor._pular_fim_de_semana(comando, sabado) is None
