"""Testes da leitura do ofício para o pedido de dilação (Fase 5).

Client OpenAI é fake (nenhuma chamada de API). O foco é a tolerância: uma resposta ruim do
modelo tem de virar análise VAZIA — que gera minuta com lacunas — e nunca derrubar a geração
no último dia do prazo.
"""
import json

from seibot import dilacao
from seibot.config import Config

CFG = Config(openai_api_key="fake", openai_model="gpt-4o-mini")

BOM = {
    "admite": True,
    "fundamento": "item 5 do Requerimento de Informações RI-II",
    "dias": 10,
    "ref_documento": "Requerimento de Informações RI-II (SEI nº 15716436)",
    "orgao": ["Gerência Regional – GR06", "Coordenação de Fiscalização Regulatória – GR06FI1"],
    "norma": "Resolução nº 746, de 22 de junho de 2021",
    "justificativa": ["Primeiro parágrafo.", "Segundo parágrafo."],
    "cidade": "Rio das Antas",
}


class _ClientFake:
    """Devolve o conteúdo combinado e guarda o que foi enviado."""

    def __init__(self, conteudo):
        self._conteudo = conteudo
        self.chamadas = []
        self.chat = self

    @property
    def completions(self):
        return self

    def create(self, **kw):
        self.chamadas.append(kw)
        msg = type("M", (), {"content": self._conteudo})
        return type("R", (), {"choices": [type("C", (), {"message": msg})]})


# ------------------------------------------------------------------ prompt (puro)
def test_prompt_leva_o_esquema_e_os_dados_ja_conhecidos():
    p = dilacao.montar_prompt("<p>Texto do of&iacute;cio</p>", {
        "processo": "53532.000310/2026-20", "empresa": "Bkup Telecom",
        "cidade_cadastro": "RIO DAS ANTAS, SC"})
    assert '"fundamento"' in p and '"justificativa"' in p
    assert "53532.000310/2026-20" in p and "Bkup Telecom" in p
    assert "RIO DAS ANTAS, SC" in p
    # o HTML do SEI é limpo antes de ir ao modelo
    assert "Texto do ofício" in p and "<p>" not in p


def test_prompt_omite_bloco_de_conhecidos_quando_nao_ha_nenhum():
    assert "DADOS JÁ CONHECIDOS" not in dilacao.montar_prompt("texto", {})


# ------------------------------------------------------------------ interpretação
def test_interpreta_resposta_completa():
    a = dilacao.interpretar(json.dumps(BOM))
    assert a.admite and a.dias == 10 and not a.vazia
    assert a.fundamento.startswith("item 5")
    assert len(a.orgao) == 2 and len(a.justificativa) == 2
    assert a.cidade == "Rio das Antas"


def test_json_invalido_vira_analise_vazia_em_vez_de_excecao():
    """Uma minuta com lacunas é entregável; uma exceção deixaria o Jurídico sem peça."""
    for ruim in ("", "isto não é json", "[1,2,3]", None):
        a = dilacao.interpretar(ruim)
        assert a.vazia and a.dias == 0 and a.justificativa == ()


def test_resposta_sem_nada_aproveitavel_conta_como_vazia():
    """`{"admite": true}` sozinho não dá nada à peça — tratar como 'não leu' faz o log
    dizer a verdade e a minuta sair com as lacunas certas."""
    a = dilacao.interpretar('{"admite": true}')
    assert a.vazia


def test_campos_ausentes_viram_vazio_sem_quebrar_o_que_veio():
    a = dilacao.interpretar('{"admite": true, "dias": 10}')
    assert a.admite and a.dias == 10 and not a.vazia
    assert a.fundamento == "" and a.orgao == () and a.justificativa == ()


def test_tolera_string_onde_o_esquema_pede_lista():
    a = dilacao.interpretar('{"justificativa": "um parágrafo só", "orgao": ""}')
    assert a.justificativa == ("um parágrafo só",) and a.orgao == ()


def test_dias_ilegivel_vira_zero():
    assert dilacao.interpretar('{"dias": "dez"}').dias == 0
    assert dilacao.interpretar('{"dias": -5}').dias == 0
    assert dilacao.interpretar('{"dias": "15"}').dias == 15


# ------------------------------------------------------------------ analisar
def test_analisar_usa_json_mode_e_o_modelo_da_config():
    cli = _ClientFake(json.dumps(BOM))
    a = dilacao.analisar("texto do ofício", CFG, client=cli)
    assert a.dias == 10
    kw = cli.chamadas[0]
    assert kw["response_format"] == {"type": "json_object"}
    assert kw["model"] == "gpt-4o-mini"


def test_sem_texto_do_oficio_nao_chama_o_llm():
    """Sem texto ele só poderia inventar. A minuta sai mesmo assim, com lacunas."""
    cli = _ClientFake(json.dumps(BOM))
    a = dilacao.analisar("   ", CFG, client=cli)
    assert a.vazia and cli.chamadas == []
