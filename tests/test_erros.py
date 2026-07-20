"""Testes da rede de segurança de erros (execução automática da Fase 2)."""
from seibot import erros


class _Cfg:
    teams_webhook_erros_url = ""
    teams_webhook_url = ""
    teams_webhook_style = "text"


def _erro(msg="boom"):
    try:
        raise ValueError(msg)
    except ValueError as e:
        return e


def test_formata_com_traceback_e_contexto():
    m = erros.formatar_erro("tratar --modo real", _erro("falhou o login"))
    assert "ERRO no monitorSEI" in m
    assert "tratar --modo real" in m
    assert "ValueError" in m and "falhou o login" in m
    assert "<pre>" in m  # traceback embutido


def test_critico_pede_acao_manual():
    m = erros.formatar_erro("x", _erro(), critico=True)
    assert "CRÍTICO" in m and "AÇÃO MANUAL" in m


def test_escapa_html_da_mensagem():
    m = erros.formatar_erro("ctx", _erro("<script>alert(1)</script>"))
    assert "<script>" not in m and "&lt;script&gt;" in m


def test_trunca_traceback_gigante():
    e = _erro("x" * 9000)
    m = erros.formatar_erro("ctx", e)
    assert "truncado" in m and len(m) < 12000


def test_usa_webhook_de_erros_quando_definido():
    cfg = _Cfg()
    cfg.teams_webhook_erros_url = "https://erros"
    cfg.teams_webhook_url = "https://grupo"
    assert erros._url_erros(cfg) == "https://erros"


def test_cai_no_webhook_do_grupo_se_erros_vazio():
    cfg = _Cfg()
    cfg.teams_webhook_url = "https://grupo"
    assert erros._url_erros(cfg) == "https://grupo"


def test_sem_webhook_nao_envia_e_nao_levanta():
    assert erros.notificar_erro(_Cfg(), "ctx", _erro(), log=lambda *a: None) is False


def test_falha_no_webhook_nao_propaga(monkeypatch):
    """Avisar sobre erro não pode virar um segundo erro que derruba o processo."""
    cfg = _Cfg()
    cfg.teams_webhook_url = "https://grupo"

    def _explode(*a, **k):
        raise ConnectionError("rede caiu")

    monkeypatch.setattr(erros, "enviar_teams_webhook", _explode)
    assert erros.notificar_erro(cfg, "ctx", _erro(), log=lambda *a: None) is False
