"""Testes da rede de segurança de erros (execução automática da Fase 2)."""
from seibot import erros


class _Cfg:
    teams_dev_email = ""
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


def test_erro_vai_para_a_DM_quando_ha_dev_email(monkeypatch):
    cfg = _Cfg()
    cfg.teams_dev_email = "gabriel.albuquerque@scmengenharia.com.br"
    cfg.teams_webhook_erros_url = "https://webhook"
    enviados = []
    import seibot.teams_dm as dm
    monkeypatch.setattr(dm, "enviar_dm", lambda c, corpo, **k: enviados.append(corpo))
    monkeypatch.setattr(erros, "enviar_teams_webhook",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("não usar webhook")))

    assert erros.notificar_erro(cfg, "ctx", _erro(), log=lambda *a: None) is True
    assert len(enviados) == 1 and "ERRO no monitorSEI" in enviados[0]


def test_nunca_manda_erro_para_o_grupo_do_juridico():
    """O webhook do grupo NÃO é fallback de erro — erro de automação é ruído p/ o Jurídico."""
    cfg = _Cfg()
    cfg.teams_webhook_url = "https://grupo"
    assert erros._url_erros(cfg) == ""
    assert erros.notificar_erro(cfg, "ctx", _erro(), log=lambda *a: None) is False


def test_webhook_de_erros_e_usado_se_nao_ha_dev_email(monkeypatch):
    cfg = _Cfg()
    cfg.teams_webhook_erros_url = "https://erros"
    urls = []
    monkeypatch.setattr(erros, "enviar_teams_webhook",
                        lambda url, corpo, style="text", **k: urls.append(url))
    assert erros.notificar_erro(cfg, "ctx", _erro(), log=lambda *a: None) is True
    assert urls == ["https://erros"]


def test_falha_da_DM_nao_propaga(monkeypatch):
    """Token delegado expirado não pode derrubar o processo nem esconder o erro original."""
    cfg = _Cfg()
    cfg.teams_dev_email = "gabriel.albuquerque@scmengenharia.com.br"
    import seibot.teams_dm as dm
    monkeypatch.setattr(dm, "enviar_dm",
                        lambda *a, **k: (_ for _ in ()).throw(dm.TeamsDMError("token morto")))
    logs = []
    assert erros.notificar_erro(cfg, "ctx", _erro("falha real"), log=logs.append) is False
    juntos = " ".join(logs)
    assert "FALHOU ao mandar DM" in juntos
    assert "falha real" in juntos  # o erro original continua visível no log


def test_sem_nada_configurado_nao_envia_e_nao_levanta():
    assert erros.notificar_erro(_Cfg(), "ctx", _erro(), log=lambda *a: None) is False


def test_falha_no_webhook_nao_propaga(monkeypatch):
    """Avisar sobre erro não pode virar um segundo erro que derruba o processo."""
    cfg = _Cfg()
    cfg.teams_webhook_url = "https://grupo"

    def _explode(*a, **k):
        raise ConnectionError("rede caiu")

    monkeypatch.setattr(erros, "enviar_teams_webhook", _explode)
    assert erros.notificar_erro(cfg, "ctx", _erro(), log=lambda *a: None) is False
