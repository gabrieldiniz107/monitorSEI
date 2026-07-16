"""Testes do módulo de resumo (OpenAI) — com cliente FAKE (sem rede/API)."""
from dataclasses import replace
from types import SimpleNamespace

from seibot.config import Config
from seibot.resumo import limpar, montar_prompt, resumir


def _cfg(**over):
    return replace(Config(), openai_api_key="x", openai_model="gpt-4o-mini", **over)


class _FakeOpenAI:
    """Imita client.chat.completions.create(...)."""
    def __init__(self, resposta="  Resumo gerado.  "):
        self.resposta = resposta
        self.capturado = None
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.capturado = kwargs
        msg = SimpleNamespace(content=self.resposta)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


def test_limpar_tira_tags_e_entidades():
    assert limpar("<p>Benef&iacute;cio &nbsp; Fiscal</p>") == "Benefício Fiscal"


def test_montar_prompt_inclui_texto_e_anexos():
    p = montar_prompt("<p>Conteúdo do ofício</p>", anexos=["Ata (15963829)"])
    assert "Conteúdo do ofício" in p
    assert "Ata (15963829)" in p
    assert "TEXTO DO OFÍCIO" in p


def test_resumir_usa_cliente_injetado_e_modelo_certo():
    fake = _FakeOpenAI("  Resumo X.  ")
    out = resumir("<p>ofício</p>", _cfg(), client=fake)
    assert out == "Resumo X."                       # strip aplicado
    assert fake.capturado["model"] == "gpt-4o-mini"  # modelo do cfg
    # a mensagem do usuário deve conter o texto do ofício
    msgs = fake.capturado["messages"]
    assert any("ofício" in m["content"] for m in msgs)
