"""Fase 5 — leitura do ofício para fundamentar o pedido de dilação de prazo (OpenAI).

Espelha `resumo.py`: prompt puro, `client` injetável (os testes usam fake, sem gastar API),
e nenhum acesso ao SEI. A diferença é o formato: aqui a saída é **JSON estruturado**
(`response_format={"type":"json_object"}`), porque cada campo vai para um lugar específico
da peça — e um campo que o modelo não achou precisa virar **lacuna marcada**, não texto
inventado.

O que se extrai vem do template real (`BKUP_TELECOM_Pedido_Dilacao_Prazo_RI_II.pdf`):

- o **fundamento** que autoriza a dilação (ex.: *"item 5 do Requerimento de Informações
  RI-II"*) — é a cláusula que o próprio ofício/RI traz;
- o **teto de dias** admitido (no template, "período não superior ao originalmente concedido");
- o **órgão** destinatário da petição (Gerência Regional / Coordenação), que sai do cabeçalho
  e da assinatura do ofício;
- a **norma** citada (ex.: Resolução nº 746/2021);
- a **justificativa** — a única parte redigida pelo modelo, e a razão de a entrega ser uma
  *minuta para revisão humana*, nunca um protocolo automático.

⚠️ Regra de ouro do prompt: **não inventar**. Campo não encontrado volta vazio/0, e a minuta
o substitui por `[PREENCHER: …]`. Uma lacuna visível é revisável; um dado plausível e falso,
numa peça que vai à Anatel, não.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional

from .config import Config
from .resumo import limpar

_SISTEMA = (
    "Você é assistente jurídico da SCM Engenharia, que representa provedores de internet "
    "(ISPs) perante a Anatel. Sua tarefa é ler um ofício/intimação da Anatel e extrair os "
    "elementos necessários para redigir um PEDIDO DE DILAÇÃO DE PRAZO. "
    "Responda SEMPRE em JSON válido, em português. "
    "NUNCA invente: se a informação não estiver no texto, devolva string vazia ou 0. "
    "É preferível um campo vazio a um dado plausível e incorreto — o campo vazio será "
    "preenchido por um advogado, o dado errado seria protocolado."
)

_ESQUEMA = """Devolva um objeto JSON com exatamente estas chaves:

{
  "admite": true|false,        // o texto traz cláusula que autoriza pedir dilação/prorrogação?
  "fundamento": "",            // a cláusula que autoriza, JÁ COM a preposição contraída,
                               // porque ela entra depois de "com fundamento ".
                               // ex.: "no item 5 do Requerimento de Informações RI-II",
                               //      "nas orientações constantes do Manual anexo"
  "dias": 0,                   // teto de dias admitido para a dilação. 0 se não disser.
  "ref_documento": "",         // o documento que fixou o prazo, com o SEI.
                               // ex.: "Requerimento de Informações RI-II (SEI nº 15716436)"
  "orgao": [],                 // linhas do órgão destinatário, do cabeçalho/assinatura do
                               // ofício. ex.: ["Gerência Regional nos Estados de Pernambuco,
                               // Paraíba e Alagoas – GR06", "Coordenação de Fiscalização
                               // Regulatória – GR06FI1"]
  "norma": "",                 // norma de regência citada, também JÁ COM a preposição
                               // contraída (entra depois de "e "). ex.: "no Regulamento de
                               // Fiscalização Regulatória, aprovado pela Resolução nº 746,
                               // de 22 de junho de 2021"
  "justificativa": [],         // 2 a 4 parágrafos justificando a necessidade de mais prazo,
                               // ancorados no que o ofício EFETIVAMENTE exige (volume de
                               // documentos, dependência de terceiros, abrangência temporal).
                               // Sem promessas concretas que você não possa sustentar.
  "cidade": ""                 // devolva a cidade informada em CIDADE DO CLIENTE com a
                               // grafia correta (acentuada e capitalizada). Vazio se não vier.
}"""


@dataclass(frozen=True)
class Analise:
    """O que o LLM conseguiu extrair. Tudo opcional — vazio vira lacuna na minuta."""
    admite: bool = False
    fundamento: str = ""
    dias: int = 0
    ref_documento: str = ""
    orgao: tuple[str, ...] = ()
    norma: str = ""
    justificativa: tuple[str, ...] = ()
    cidade: str = ""
    # marca as análises que não passaram pelo LLM (ofício sem dossiê guardado)
    vazia: bool = field(default=False)


ANALISE_VAZIA = Analise(vazia=True)


def montar_prompt(oficio_texto: str, contexto: Optional[dict] = None) -> str:
    """Prompt puro (testável sem API). `contexto` = dados que o bot já conhece do processo."""
    ctx = contexto or {}
    partes = [_ESQUEMA, ""]
    dados = [
        ("PROCESSO", ctx.get("processo")),
        ("OFÍCIO", ctx.get("oficio_desc")),
        ("EMPRESA (requerente)", ctx.get("empresa")),
        ("CIDADE DO CLIENTE", ctx.get("cidade_cadastro")),
        ("PRAZO ORIGINAL", ctx.get("prazo_texto")),
        ("DOCUMENTOS DO PROCESSO", ctx.get("protocolos_texto")),
    ]
    conhecidos = [f"{r}: {v}" for r, v in dados if v]
    if conhecidos:
        partes.append("DADOS JÁ CONHECIDOS (use-os, não os contradiga):")
        partes.extend(conhecidos)
        partes.append("")
    partes.append("TEXTO DO OFÍCIO:")
    partes.append(limpar(oficio_texto))
    return "\n".join(partes)


def _lista(valor) -> tuple[str, ...]:
    """Tolerante: o modelo às vezes devolve string única onde o esquema pede lista."""
    if isinstance(valor, str):
        valor = [valor] if valor.strip() else []
    if not isinstance(valor, (list, tuple)):
        return ()
    return tuple(str(x).strip() for x in valor if str(x).strip())


def _inteiro(valor) -> int:
    try:
        return max(0, int(str(valor).strip()))
    except (TypeError, ValueError):
        return 0


def interpretar(bruto: str) -> Analise:
    """JSON do modelo → `Analise`. **Nunca levanta**: resposta ruim vira análise vazia.

    Uma minuta com lacunas é entregável; uma exceção aqui derrubaria a geração inteira e o
    Jurídico ficaria sem peça nenhuma no último dia do prazo.
    """
    try:
        d = json.loads(bruto or "{}")
    except (ValueError, TypeError):
        return ANALISE_VAZIA
    if not isinstance(d, dict):
        return ANALISE_VAZIA
    a = Analise(
        admite=bool(d.get("admite")),
        fundamento=str(d.get("fundamento") or "").strip(),
        dias=_inteiro(d.get("dias")),
        ref_documento=str(d.get("ref_documento") or "").strip(),
        orgao=_lista(d.get("orgao")),
        norma=str(d.get("norma") or "").strip(),
        justificativa=_lista(d.get("justificativa")),
        cidade=str(d.get("cidade") or "").strip(),
    )
    # JSON válido mas sem nada aproveitável (`{}`, ou o modelo devolvendo tudo vazio) é,
    # para efeito da minuta, o mesmo que não ter lido: marcar `vazia` faz o log dizer a
    # verdade e a peça sair com as lacunas certas.
    if not any((a.fundamento, a.dias, a.ref_documento, a.orgao, a.norma,
                a.justificativa, a.cidade)):
        return ANALISE_VAZIA
    return a


def analisar(oficio_texto: str, cfg: Config, *, contexto: Optional[dict] = None,
             client=None) -> Analise:
    """Lê o ofício e devolve os elementos da peça. Sem texto guardado ⇒ análise vazia.

    Não chamar o LLM sem texto é de propósito: ele só poderia inventar. A minuta é gerada
    mesmo assim (decisão do usuário), toda a parte variável em lacunas.
    """
    if not (oficio_texto or "").strip():
        return ANALISE_VAZIA
    from .resumo import _client
    client = client or _client(cfg)
    resp = client.chat.completions.create(
        model=cfg.openai_model,
        temperature=0.2,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": _SISTEMA},
            {"role": "user", "content": montar_prompt(oficio_texto, contexto)},
        ],
    )
    return interpretar(resp.choices[0].message.content or "")
