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

**A cadência é ancorada no VENCIMENTO** (`dias_restantes % intervalo == 0`), não na data da
ciência. Assim o dia da data limite sempre é coberto, e o aviso fala em "faltam X dias", que
é o que interessa a quem lê. Consequência a não estranhar: num prazo de 22 dias (intervalo 4)
o primeiro aviso sai quando faltam 20, não 22.

**Aviso que cairia em sábado ou domingo é ANTECIPADO para a sexta anterior** (decisão do
usuário, 2026-08-05). Antecipar preserva o prazo restante; empurrar para a segunda o
consumiria. Sem isso o alerta mais crítico caía em fim de semana com frequência — num prazo
de 20 dias iniciado numa sexta, a "última chance" caía num domingo. Prazo VENCIDO também só
é avisado em dia útil (ele insiste todo dia, então a segunda cobre o fim de semana).

**"Última chance"** = não há mais nenhum aviso agendado **antes** do dia do vencimento. É o
último momento em que ainda dá para montar defesa ou pedir dilação de prazo — e é o gancho
onde essa automação futura vai se plugar. O próprio dia do vencimento não conta como "mais um
aviso" justamente porque ali já é tarde para isso.

Cadência em **dias corridos** (decisão do usuário): a data limite já vem pronta da Anatel,
então ela está sempre certa; só o intervalo entre lembretes é de calendário, o que evita
depender de tabela de feriados.
"""
from __future__ import annotations

import html as _html
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

from .datas import de_ddmmaaaa, eh_dia_util

_SEXTA = 4

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
    ultima_chance: bool = False   # não há mais aviso agendado antes do vencimento
    vencido: bool = False
    antecipado: bool = False      # o checkpoint caía no fim de semana e veio para hoje


def _dispara_em(limite: date, dia: date, intervalo: int) -> bool:
    """Este dia dispara aviso, considerando a antecipação de fim de semana?

    Um checkpoint que cai em sábado ou domingo é **antecipado para a sexta anterior**
    (decisão do usuário, 2026-08-05). Antecipar preserva o prazo restante; empurrar para
    a segunda o consumiria — e o aviso mais crítico ("última chance para defesa ou
    dilação") era justamente o que mais caía em fim de semana.
    """
    if not eh_dia_util(dia):
        return False
    # a sexta responde também pelos checkpoints do sábado e do domingo seguintes
    extras = (1, 2) if dia.weekday() == _SEXTA else ()
    for delta in (0, *extras):
        faltam = (limite - (dia + timedelta(days=delta))).days
        if faltam >= 0 and faltam % intervalo == 0:
            return True
    return False


def _ha_aviso_antes_do_vencimento(limite: date, depois_de: date, intervalo: int) -> bool:
    """Ainda sobra algum aviso agendado entre amanhã e a véspera do vencimento?

    O dia do vencimento **não** conta: naquele momento já não dá para montar defesa nem
    pedir dilação, que é justamente o que o alerta de "última chance" existe para permitir.
    """
    dia = depois_de + timedelta(days=1)
    while dia < limite:
        if _dispara_em(limite, dia, intervalo):
            return True
        dia += timedelta(days=1)
    return False


def decidir(data_limite: str, prazo_dias: Optional[int], hoje: date,
            ja_avisou_hoje: bool = False) -> Optional[Decisao]:
    """Decide se hoje é dia de avisar. `None` se não há data limite para contar."""
    limite = de_ddmmaaaa(data_limite)
    if limite is None:
        return None
    faltam = (limite - hoje).days
    intervalo = intervalo_de(prazo_dias)

    if faltam < 0:
        # vencido e ainda na raia: insiste todo DIA ÚTIL até alguém mover o card. É o pior
        # cenário do sistema — não pode virar um aviso único que passe despercebido.
        return Decisao(avisar=eh_dia_util(hoje) and not ja_avisou_hoje,
                       faltam=faltam, vencido=True)

    if not _dispara_em(limite, hoje, intervalo):
        return Decisao(avisar=False, faltam=faltam)
    return Decisao(
        avisar=not ja_avisou_hoje,
        faltam=faltam,
        # "última chance" = não há mais nenhum aviso agendado antes do vencimento. Definir
        # assim (em vez de "faltam == intervalo") mantém o alerta correto quando o próprio
        # vencimento cai em fim de semana e a sexta passa a ser o último aviso possível.
        ultima_chance=faltam > 0 and not _ha_aviso_antes_do_vencimento(limite, hoje, intervalo),
        antecipado=(faltam % intervalo != 0),
    )


# ----------------------------------------------------------------------------
# Mensagens (HTML — o fluxo do Power Automate posta como HTML)
# ----------------------------------------------------------------------------
def _esc(s: object) -> str:
    return _html.escape(str(s), quote=False)


def eh_coletivo(linha: dict) -> bool:
    return (linha.get("grupo_tipo") or "individual") == "coletivo"


def _cabecalho(linha: dict) -> list:
    # No coletivo o ofício é um só para N empresas — o aviso é por OFÍCIO, então listar
    # "Empresa: fulana" seria enganoso (e sairia N vezes). Ver `monitor.acompanhar_prazos`.
    if eh_coletivo(linha):
        empresa = (f"<b>Empresas:</b> {_esc(linha.get('empresas') or '?')} "
                   "(ofício coletivo)")
    else:
        # linhas antigas (anteriores à coluna `empresa`) vêm com NULL — "Empresa: None" na
        # mensagem do Jurídico parece bug do bot
        empresa = f"<b>Empresa:</b> {_esc(linha.get('empresa') or '—')}"
    return [
        f"<b>Processo:</b> {_esc(linha.get('processo'))}",
        f"<b>Ofício:</b> {_esc(linha.get('oficio_desc') or 'Ofício')} "
        f"({_esc(linha.get('doc_id'))})",
        empresa,
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
    if d.antecipado:
        linhas.append("📅 <i>Aviso antecipado: a verificação cairia em fim de semana.</i>")
    if d.vencido:
        linhas.append("👉 Mover o card para encerrar os avisos.")
    elif d.ultima_chance or d.faltam == 0:
        linhas.append("👉 Último momento para montar defesa ou pedir dilação de prazo.")
    elif eh_coletivo(linha):
        linhas.append("👉 Os clientes ainda não enviaram a documentação.")
    else:
        linhas.append("👉 Cliente ainda não enviou a documentação.")
    pasta = linha.get("pasta_url") or ""
    if pasta:
        # sem escape: escapar o '&' quebraria o link do SharePoint (mesmo motivo do coletivo)
        linhas.append(f'📁 <a href="{pasta}">Pasta compartilhada com os clientes</a>')
    return "<br>".join(linhas)


def formatar_minuta_dilacao(linha: dict, url: str, minuta, pasta_url: str = "",
                            extras: int = 0) -> str:
    """Avisa que a minuta de dilação foi gerada e onde ela está.

    Mensagem **separada** do lembrete de prazo de propósito: se a geração falhar, o aviso de
    última chance sai intacto — ele é o que não pode faltar.
    """
    linhas = ["📄 <b>Minuta de pedido de dilação de prazo gerada</b>"] + _cabecalho(linha)
    linhas.append(f"<b>Vencimento:</b> {_esc(linha.get('data_limite'))}")
    if minuta.dias_pedidos:
        unidade = (linha.get("prazo_unidade") or "dias").strip() or "dias"
        linhas.append(f"<b>Dilação requerida:</b> {minuta.dias_pedidos} {_esc(unidade)}")
    if minuta.admite_dilacao is False:
        # o modelo leu o ofício e NÃO achou cláusula que autorize dilação (ex.: Notificação
        # de Lançamento tributária, cujo remédio é impugnação). A peça é gerada assim mesmo
        # — decisão do usuário —, mas protocolar sem conferir seria pedir indeferimento.
        linhas.append("🛑 <b>Atenção:</b> não foi encontrada no ofício cláusula que autorize "
                      "dilação de prazo. Conferir se o pedido cabe neste caso — pode ser que "
                      "o remédio correto seja outro (impugnação, recurso).")
    elif minuta.admite_dilacao is None:
        linhas.append("ℹ️ <i>O texto do ofício não estava guardado: a minuta saiu no modelo "
                      "padrão, sem leitura do caso.</i>")
    if minuta.lacunas:
        linhas.append(f"⚠️ <b>{len(minuta.lacunas)} lacuna(s)</b> a preencher: "
                      + _esc(", ".join(minuta.lacunas)))
        linhas.append("Buscar por <b>[PREENCHER: …]</b> no documento.")
    # os dois links, de propósito (pedido do usuário): o arquivo abre direto no Word para
    # revisar; a pasta é onde ficam as versões ajustadas e o resto do caso.
    # Sem escape: escapar o '&' quebraria o link do SharePoint.
    if url:
        linhas.append(f'📝 <a href="{url}">Abrir a minuta (Word)</a>')
    if pasta_url:
        junto = (f" — com o ofício e {extras - 1} anexo(s) para conferência"
                 if extras > 1 else " — com o ofício para conferência" if extras == 1 else "")
        linhas.append(f'📁 <a href="{pasta_url}">Abrir a pasta da minuta</a>{junto}')
    linhas.append("👉 <b>Revisar, ajustar e protocolar no SEI.</b> A automação "
                  "<b>não</b> peticiona — e o pedido de dilação não suspende nem interrompe "
                  "o prazo, então os lembretes continuam até o card sair da raia.")
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
