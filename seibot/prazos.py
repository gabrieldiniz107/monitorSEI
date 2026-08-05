"""Acompanhamento de prazos — decide QUANDO avisar e monta a mensagem. Puro, sem I/O.

Regra da cadência (definida pelo Jurídico, 2026-08-05):

| Prazo do ofício | Avisa a cada |
|---|---|
| 5 dias  | 1 dia (todo dia) |
| 10 dias | 2 dias |
| 15 dias | 3 dias |
| 20 dias | 4 dias |
| 30 dias | 5 dias |

Prazo fora da tabela **arredonda para o mapeado imediatamente inferior**: 6 dias usa a
regra de 5 (avisa todo dia), 12 usa a de 10 (de 2 em 2), 25 usa a de 20, 45 usa a de 30.
Abaixo de 5 dias, avisa todo dia.

**A cadência é ancorada no VENCIMENTO, contando de trás para frente** — não na data da
ciência. Assim todo prazo ganha uma verificação exatamente na data limite, e o aviso fala
em "faltam X dias", que é o que interessa a quem lê. Nos prazos mapeados dá no mesmo (5, 10,
15, 20 e 30 são todos divisíveis pelo próprio intervalo); a diferença aparece nos
arredondados — um prazo de 22 dias vira intervalo 4 e cai em 22, 18, 14, 10, 6, 2 e 0.

A **última verificação antes do vencimento** (`faltam == intervalo`) sai marcada como tal:
é o momento em que o Jurídico ainda consegue montar defesa ou pedir dilação de prazo — e é
o gancho onde essa automação futura vai se plugar.

Cadência em **dias corridos** (decisão do usuário): a data limite já vem pronta da Anatel,
então ela está sempre certa; só o intervalo entre lembretes é de calendário, o que evita
depender de tabela de feriados.
"""
from __future__ import annotations

import html as _html
from dataclasses import dataclass
from datetime import date
from typing import Optional

from .datas import de_ddmmaaaa

# prazo do ofício (dias) -> intervalo entre avisos (dias)
ESCADA = {5: 1, 10: 2, 15: 3, 20: 4, 30: 5}
_DEGRAUS = sorted(ESCADA)

# raia do Kanban que mantém a contagem viva
from .oficio_card import STATUS_AGUARDANDO  # noqa: E402  (evita ciclo: oficio_card não importa daqui)

# motivos de parada da contagem
PARADA_SAIU_DA_RAIA = "saiu de '" + STATUS_AGUARDANDO + "' no Kanban"
PARADA_SEM_CARD = "sem card no Controle de Ofício — não dá para saber a raia"


def intervalo_de(prazo_dias: Optional[int]) -> int:
    """Intervalo entre avisos para um prazo, arredondando para o degrau inferior.

    `None` (prazo antigo recuperado pelo backfill, que só trouxe a data) cai no degrau
    mais conservador: avisa todo dia. Melhor pecar por insistência do que perder prazo.
    """
    if not prazo_dias or prazo_dias < _DEGRAUS[0]:
        return ESCADA[_DEGRAUS[0]]
    degrau = max(d for d in _DEGRAUS if d <= prazo_dias)
    return ESCADA[degrau]


@dataclass(frozen=True)
class Decisao:
    """O que fazer hoje com um prazo em acompanhamento."""
    avisar: bool
    faltam: int              # dias até o vencimento (negativo = vencido)
    ultima_chance: bool = False   # última verificação ANTES do vencimento
    vencido: bool = False


def decidir(data_limite: str, prazo_dias: Optional[int], hoje: date,
            ja_avisou_hoje: bool = False) -> Optional[Decisao]:
    """Decide se hoje é dia de avisar. `None` se não há data limite para contar."""
    limite = de_ddmmaaaa(data_limite)
    if limite is None:
        return None
    faltam = (limite - hoje).days
    intervalo = intervalo_de(prazo_dias)

    if faltam < 0:
        # vencido e ainda na raia: insiste todo dia até alguém mover o card. É o pior
        # cenário do sistema — não pode virar um aviso único que passe despercebido.
        return Decisao(avisar=not ja_avisou_hoje, faltam=faltam, vencido=True)
    avisar = (faltam % intervalo == 0) and not ja_avisou_hoje
    return Decisao(avisar=avisar, faltam=faltam,
                   ultima_chance=(faltam == intervalo))


# ----------------------------------------------------------------------------
# Mensagens (HTML — o fluxo do Power Automate posta como HTML)
# ----------------------------------------------------------------------------
def _esc(s: object) -> str:
    return _html.escape(str(s), quote=False)


def _cabecalho(linha: dict) -> list:
    return [
        f"<b>Processo:</b> {_esc(linha.get('processo'))}",
        f"<b>Ofício:</b> {_esc(linha.get('oficio_desc') or 'Ofício')} "
        f"({_esc(linha.get('doc_id'))})",
        f"<b>Empresa:</b> {_esc(linha.get('empresa'))}",
    ]


def formatar_aviso(linha: dict, d: Decisao) -> str:
    """Lembrete de prazo em aberto (card ainda em 'Aguardando documentação (cliente)')."""
    if d.vencido:
        dias = abs(d.faltam)
        topo = (f"🆘 <b>PRAZO VENCIDO há {dias} dia(s)</b>"
                if dias > 1 else "🆘 <b>PRAZO VENCIDO ontem</b>")
    elif d.faltam == 0:
        topo = "🔴 <b>PRAZO VENCE HOJE</b>"
    elif d.ultima_chance:
        topo = f"🟠 <b>ÚLTIMA verificação — faltam {d.faltam} dia(s)</b>"
    else:
        topo = f"⏳ <b>Prazo em aberto — faltam {d.faltam} dia(s)</b>"

    linhas = [topo] + _cabecalho(linha)
    linhas.append(f"<b>Vencimento:</b> {_esc(linha.get('data_limite'))}")
    linhas.append(f"<b>Kanban:</b> {_esc(STATUS_AGUARDANDO)}")
    if d.vencido:
        linhas.append("👉 Mover o card para encerrar os avisos.")
    elif d.ultima_chance or d.faltam == 0:
        linhas.append("👉 Último momento para montar defesa ou pedir dilação de prazo.")
    else:
        linhas.append("👉 Cliente ainda não enviou a documentação.")
    return "<br>".join(linhas)


def formatar_parada(linha: dict, motivo: str, status_atual: str = "") -> str:
    """Avisa que a automação PAROU de contar. Não significa processo resolvido —
    só que o gatilho da contagem (a raia do Kanban) deixou de valer."""
    linhas = ["⏹️ <b>Contagem de prazo encerrada pela automação</b>"] + _cabecalho(linha)
    linhas.append(f"<b>Vencimento:</b> {_esc(linha.get('data_limite'))}")
    if status_atual:
        linhas.append(f"<b>Kanban agora:</b> {_esc(status_atual)}")
    linhas.append(f"<b>Motivo:</b> {_esc(motivo)}")
    linhas.append("ℹ️ Isto <b>não</b> marca o processo como resolvido — "
                  "apenas encerra os avisos automáticos de prazo.")
    return "<br>".join(linhas)


def formatar_sem_card(linha: dict) -> str:
    """Tem prazo, mas não há card no Kanban — sem a raia não dá para contar nem parar."""
    linhas = ["⚠️ <b>Prazo sem card no Controle de Ofício</b>"] + _cabecalho(linha)
    linhas.append(f"<b>Vencimento:</b> {_esc(linha.get('data_limite'))}")
    linhas.append("Sem card não há raia para consultar, então a automação <b>não</b> "
                  "consegue acompanhar este prazo.")
    linhas.append("👉 Criar o card à mão para o acompanhamento voltar a valer.")
    return "<br>".join(linhas)
