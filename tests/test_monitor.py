"""Testes do orquestrador executar() com fakes (coletar/enviar) + store real em tmp_path."""
from dataclasses import replace

import pytest

from seibot import monitor
from seibot.config import Config
from seibot.models import Intimacao
from seibot.store import IntimacoesStore


def _cfg(**over):
    return replace(Config(), **over)


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
