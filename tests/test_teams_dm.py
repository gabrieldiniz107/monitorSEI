"""Testes das partes puras da DM no Teams (Graph delegado)."""
import base64
import json

import pytest

from seibot import teams_dm


class _Cfg:
    teams_dev_email = "gabriel.albuquerque@scmengenharia.com.br"
    graph_tenant_id = "t"
    graph_client_id = "c"
    graph_token_cache = "state/.graph_token.json"
    teams_chat_cache = "state/.teams_chats.json"


def _jwt(payload: dict) -> str:
    corpo = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"cabecalho.{corpo}.assinatura"


def test_ordenado_unico_dedup_case_insensitive():
    assert teams_dm.ordenado_unico(["A@x.com", "a@X.com", "b@x.com"]) == ["A@x.com", "b@x.com"]


def test_ordenado_unico_ignora_vazios():
    assert teams_dm.ordenado_unico(["", "  ", "a@x.com"]) == ["a@x.com"]


def test_self_chat_quando_destino_e_o_proprio_remetente():
    """Remetente == destino ⇒ 1 membro ⇒ o Graph exige 'group' (self-chat)."""
    assert teams_dm.ordenado_unico(["eu@x.com", "EU@x.com"]) == ["eu@x.com"]


def test_chave_do_cache_independe_de_ordem_e_caixa():
    assert teams_dm._chave(["B@x.com", "a@X.com"]) == teams_dm._chave(["a@x.com", "b@x.com"])


def test_me_upn_le_upn_do_token():
    assert teams_dm.me_upn(_jwt({"upn": "gabriel@x.com"})) == "gabriel@x.com"


def test_me_upn_aceita_preferred_username():
    assert teams_dm.me_upn(_jwt({"preferred_username": "g@x.com"})) == "g@x.com"


def test_me_upn_sem_upn_levanta():
    with pytest.raises(teams_dm.TeamsDMError):
        teams_dm.me_upn(_jwt({"sub": "123"}))


def test_enviar_dm_sem_destino_levanta():
    class _Vazio(_Cfg):
        teams_dev_email = ""

    with pytest.raises(teams_dm.TeamsDMError, match="TEAMS_DEV_EMAIL"):
        teams_dm.enviar_dm(_Vazio(), "<b>oi</b>")


def test_token_sem_cache_orienta_o_login(tmp_path):
    class _C(_Cfg):
        graph_token_cache = str(tmp_path / "nao_existe.json")

    with pytest.raises(teams_dm.TeamsDMError, match="--login"):
        teams_dm.token_graph(_C())
