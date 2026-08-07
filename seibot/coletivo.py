"""Fase 4 — tratativa de ofício COLETIVO: ciência + publicação dos documentos.

Quando o mesmo ofício atinge várias empresas, não há e-mail a mandar: a Anatel manda um
documento só, e o Jurídico o entrega pela pasta compartilhada com os clientes (ver
`biblioteca.py`). O bot faz o que era manual: **abre → dá ciência → identifica ofício,
anexos e (se houver) prazo → baixa tudo → publica na pasta do ofício → avisa o Teams**.

Diferenças deliberadas em relação à Fase 2 (`tratativa.py`), que é mono-empresa:

- **Não olha se a empresa é cliente ativo.** O ofício é indivisível e a pasta é do ofício,
  não da empresa. Basta haver um destinatário `Pendente`.
- **Não manda e-mail nem cria rascunho** — publicar na pasta é a entrega.
- **Não cria card no Kanban** e, por consequência, **não entra no acompanhamento de prazos
  da Fase 3** (que usa a raia do card como gatilho). Coletivo **tem** prazo com frequência —
  os 9 da janela de 07/08/2026 eram todos URGENTE, 5 dias — e ele vai destacado com ⚠️ na
  mensagem do Teams, que é onde o Jurídico o controla à mão.
- **Anexo = o que o TEXTO do ofício cita**, e não o que o SEI empacotou na intimação
  (o inverso da Fase 2). Ver o comentário em `_apos_ciencia`.

⚠️ **A ciência é irreversível.** Vale aqui a mesma disciplina do `tratar_um`: capturar os
documentos da intimação ANTES (os ícones somem depois), gravar checkpoint logo após a
ciência, e classificar falha pós-ciência como `TratativaIncompleta` (alerta crítico).
"""
from __future__ import annotations

from typing import Optional

from .models import Grupo
from .tratativa import SITUACAO_PENDENTE, TratativaIncompleta

# teto do laço de ciência: no pior caso (ciência por destinatário) são N aceites; a folga
# de +1 dá margem sem virar laço infinito se a página parar de mudar.
FOLGA_CIENCIA = 1

# por que o coletivo sai do acompanhamento de prazos assim que é registrado
MOTIVO_SEM_CARD = "coletivo — sem card no Kanban, prazo acompanhado pelo Jurídico"

# quantas empresas listar por extenso na mensagem antes de resumir "(+X)" — igual ao notify
MAX_EMPRESAS_LISTADAS = 15


def motivo_nao_candidato(g: Grupo, *, ja_tratado: bool = False) -> Optional[str]:
    """Motivo para NÃO tratar este grupo — `None` significa "pode tratar".

    Devolve texto (e não um bool) de propósito: toda recusa precisa ser explicável no log.
    Foi um descarte silencioso que fez a intimação da Age Telecomunicações sumir sem que
    ninguém soubesse (incidente de 05/08/2026).
    """
    if g.tipo != "coletivo":
        return "ofício individual — é da Fase 2 (tratativa individual)"
    if ja_tratado:
        return "ofício já tratado (registrado no store)"
    if not any(i.situacao == SITUACAO_PENDENTE for i in g.destinatarios):
        situacoes = sorted({i.situacao for i in g.destinatarios})
        return f"nenhum destinatário Pendente (situações: {', '.join(situacoes)})"
    return None


def selecionar_candidatos(grupos, store=None) -> list:
    def tratado(g: Grupo) -> bool:
        return bool(store) and all(store.ja_tratado(i.chave) for i in g.destinatarios)
    return [g for g in grupos if motivo_nao_candidato(g, ja_tratado=tratado(g)) is None]


def mapear(sess, grupo: Grupo, log=print) -> dict:
    """READ-ONLY: abre a página e conta os ícones de aceite. **Não clica em nada.**

    Existe para responder, sem risco, a pergunta que decide o laço de ciência: um aceite
    cobre todos os destinatários do coletivo, ou há um por empresa? (A lista de intimações
    mostra grupos com situação mista, o que deixa a resposta ambígua no HTML da listagem.)
    """
    from . import processo

    intim = grupo.destinatarios[0]
    processo.abrir_processo(sess.page, intim.consulta_url)
    aceites = processo.urls_aceite(sess.page)
    pendentes = [i for i in grupo.destinatarios if i.situacao == SITUACAO_PENDENTE]

    log(f"\n===== MAPEAR (nada foi clicado) — {grupo.processo} | {grupo.oficio_desc} "
        f"({grupo.doc_id}) =====")
    log(f"  destinatários: {len(grupo.destinatarios)} | Pendentes: {len(pendentes)}")
    for i in grupo.destinatarios:
        log(f"    • {i.destinatario} — {i.documento_fmt} — {i.situacao}")
    log(f"  ícones de aceite na página: {len(aceites)}")
    for a in aceites:
        log(f"    • doc {a.get('num') or '?'}"
            + ("  [documento principal]" if a.get("principal") else "")
            + f"\n      {a.get('url', '')[:160]}")
    log("  ⇒ se nº de aceites ~= nº de documentos da intimação, UMA ciência cobre todos;\n"
        "    se ~= nº de empresas Pendentes, a ciência é por destinatário (o laço cobre).")
    return {"destinatarios": len(grupo.destinatarios), "pendentes": len(pendentes),
            "aceites": len(aceites),
            "docs": [a.get("num") for a in aceites],
            "situacoes": sorted({i.situacao for i in grupo.destinatarios})}


def _dar_ciencia_de_todos(page, grupo: Grupo, store, log) -> int:
    """Dá ciência até não sobrar ícone de aceite. Devolve quantas confirmações foram feitas.

    **Autocorretivo de propósito.** Não se sabe ao certo se uma confirmação cumpre a
    intimação para todos os destinatários do coletivo ou só para um: as linhas do mesmo
    ofício compartilham `id_intimacao`/`id_acesso_externo`, mas a Situação é por
    destinatário e existem grupos com estado misto. Reler a página depois de cada
    confirmação funciona nos dois casos — 1 volta se cobre todos, N se não cobre.
    """
    from . import processo

    intim = grupo.destinatarios[0]
    teto = len(grupo.destinatarios) + FOLGA_CIENCIA
    feitas = 0
    while True:
        aceites = processo.urls_aceite(page)
        if not aceites:
            break
        if feitas >= teto:
            raise RuntimeError(
                f"laço de ciência excedeu {teto} confirmações e a página ainda mostra "
                f"{len(aceites)} aceite(s) — abortado para não clicar indefinidamente.")
        alvo = processo.escolher_aceite(aceites, grupo.doc_id)
        log(f"   ⚠️ DANDO CIÊNCIA ({feitas + 1}ª; doc {alvo.get('num') or '?'}) — irreversível…")
        processo.dar_ciencia(page, alvo["url"])
        feitas += 1
        if feitas == 1:
            # checkpoint imediato p/ TODOS os destinatários: se o pipeline quebrar daqui pra
            # frente, nenhuma empresa deste ofício é re-tratada (ciência dupla).
            for i in grupo.destinatarios:
                store.marcar_tratado(i, "")
        processo.abrir_processo(page, intim.consulta_url)   # recarrega com os links vivos
    return feitas


# quantas releituras da página antes de desistir de achar o ícone de aceite
TENTATIVAS_ACEITE = 3


def _aceites_de_pendente(page, grupo: Grupo, log) -> list:
    """Ícones de aceite, com releitura enquanto houver destinatário Pendente sem ícone.

    ⚠️ "Sem ícone de aceite" é lido como **"ciência já dada"** — mas se o grupo ainda tem
    destinatário `Pendente`, isso é uma contradição, não um estado. Quase sempre é o
    lazy-load da coluna "Ações" que não resolveu (ver `processo._aceites_lazy`), e reabrir
    resolve. Seguir em frente é o pior desfecho possível: o bot conclui que já houve
    ciência, falha adiante em "ofício não achado na Lista de Protocolos", e a intimação
    continua Pendente sem ninguém ter dado ciência — foi o que aconteceu com os ofícios
    682 e 666 no lote de 07/08/2026. Melhor abortar alto e retentar no ciclo seguinte.
    """
    from . import processo

    pendentes = [i for i in grupo.destinatarios if i.situacao == SITUACAO_PENDENTE]
    for tentativa in range(1, TENTATIVAS_ACEITE + 1):
        try:
            aceites = processo.urls_aceite(page)
        except Exception as e:
            # "Execution context was destroyed": a página navegou enquanto líamos as ações
            # (o loader nativo do SEI faz um fetch por documento e a página se recarrega).
            # Reabrir resolve — é a mesma classe de erro que `abrir_processo` já retenta.
            if not processo._eh_erro_navegacao(e) or tentativa == TENTATIVAS_ACEITE:
                raise
            log(f"   ⚠️ a página navegou ao ler as Ações (tentativa {tentativa}/"
                f"{TENTATIVAS_ACEITE}) — recarregando…")
            processo.abrir_processo(page, grupo.destinatarios[0].consulta_url)
            continue
        if aceites or not pendentes:
            return aceites
        log(f"   ⚠️ {len(pendentes)} destinatário(s) Pendente(s) e nenhum ícone de aceite "
            f"(tentativa {tentativa}/{TENTATIVAS_ACEITE}) — recarregando a página…")
        if tentativa < TENTATIVAS_ACEITE:
            processo.abrir_processo(page, grupo.destinatarios[0].consulta_url)
    raise RuntimeError(
        f"ofício {grupo.doc_id}: {len(pendentes)} destinatário(s) Pendente(s) mas nenhum "
        f"ícone de aceite após {TENTATIVAS_ACEITE} leituras — abortado sem tocar nele "
        "(seguir daqui seria concluir, errado, que a ciência já foi dada).")


def tratar_coletivo(sess, cfg, grupo: Grupo, clientes, store, g_graph, *,
                    dar_ciencia: bool = False, publicar: bool = True,
                    url_teams: Optional[str] = None, log=print) -> dict:
    """Trata UM ofício coletivo ponta a ponta. Ver o cabeçalho do módulo para as regras."""
    from . import processo

    intim = grupo.destinatarios[0]
    page = sess.page
    log(f"→ Coletivo {grupo.processo} | {grupo.oficio_desc} ({grupo.doc_id}) | "
        f"{len(grupo.destinatarios)} empresas")

    processo.abrir_processo(page, intim.consulta_url)

    aceites = _aceites_de_pendente(page, grupo, log)

    ciencia_dada = 0
    if aceites:
        if not dar_ciencia:
            raise RuntimeError(
                f"ofício {grupo.doc_id} ainda PENDENTE (aceite não dado) e dar_ciencia=False "
                "— sem ciência não há Lista de Protocolos. Abortado sem tocar nele.")
        try:
            ciencia_dada = _dar_ciencia_de_todos(page, grupo, store, log)
        except processo.CienciaIncerta as e:
            # assume que a ciência saiu: grava o checkpoint (senão o registro se perde e o
            # ofício some da seleção sem rastro) e alerta como falha pós-ciência.
            for i in grupo.destinatarios:
                store.marcar_tratado(i, "")
            raise TratativaIncompleta(
                str(e), processo=grupo.processo,
                empresa=f"{len(grupo.destinatarios)} empresas (coletivo)") from e
        log(f"   ✓ ciência confirmada ({ciencia_dada}x)")
    else:
        log("   • sem ícone de aceite: ciência já dada fora do bot — seguindo sem dar ciência")

    try:
        return _apos_ciencia(sess, cfg, grupo, clientes, store, g_graph,
                             publicar=publicar,
                             url_teams=url_teams, ciencias=ciencia_dada, log=log)
    except Exception as e:
        if not ciencia_dada:
            raise
        # ciência já dada: o checkpoint bloqueia o retry e o documento NÃO foi publicado.
        raise TratativaIncompleta(str(e), processo=grupo.processo,
                                  empresa=f"{len(grupo.destinatarios)} empresas (coletivo)") from e


def _apos_ciencia(sess, cfg, grupo: Grupo, clientes, store, g_graph, *,
                  publicar: bool, url_teams, ciencias: int, log) -> dict:
    """Da Lista de Protocolos até o Teams. Separado para que toda falha aqui seja
    classificada como pós-ciência pelo `tratar_coletivo`."""
    from . import biblioteca, processo, resumo
    from .teams import enviar_teams_webhook

    page, ctx = sess.page, sess.context
    protos = processo.mapa_protocolos(page)
    if not protos:
        raise RuntimeError("Lista de Protocolos vazia mesmo após a ciência — abortado.")

    # coletivo normalmente não tem prazo de resposta; quando tem, é exceção e vai destacada
    resp_url = processo.url_peticionar_resposta(page)
    prazo = processo.capturar_prazo(page, resp_url) if resp_url else None
    log(f"   prazo: {prazo.data_limite if prazo else '— (sem prazo de resposta)'}")

    of = protos.get(grupo.doc_id)
    if not of:
        raise RuntimeError(f"ofício {grupo.doc_id} não achado na Lista de Protocolos")
    of_bytes = processo.baixar(ctx, of["url"])
    oficio_texto = processo.extrair_texto_oficio(of_bytes)

    # ANEXO = o que o TEXTO do ofício cita como "(SEI nº …)" — decisão do usuário em
    # 07/08/2026, e é o oposto da regra do individual (`tratativa`), que usa os documentos
    # empacotados pelo SEI na intimação. Motivo: no coletivo 693 o SEI empacotou 3 anexos,
    # mas um deles (Planilha "Tabela ISPs/Domínios", 16075319) não é do ofício e não deve ir
    # para o cliente — o ofício citava exatamente os 2 corretos.
    # ⚠️ Contrapartida aceita: ofício que esquece de citar um anexo real deixa o cliente sem
    # ele. Foi o que aconteceu no Ofício 70 do individual — e é justamente por isso que a
    # Fase 2 continua com a outra regra.
    citados = processo.extrair_anexos(oficio_texto)
    if not citados:
        log("   • o ofício não cita nenhum '(SEI nº …)' — vai só o ofício.")
    anexos_nums = processo.anexos_da_intimacao(protos, grupo.doc_id, None, citados)
    anexos: list[tuple[str, bytes]] = []
    descr: list[str] = []
    for ordem, num in enumerate(anexos_nums, start=1):
        p = protos.get(num)
        if not p:
            continue
        # baixar_como_pdf, não baixar cru: documentos gerados no SEI vêm em HTML e, salvos
        # como .pdf, não abrem (incidente da SITELBRA).
        anexos.append((biblioteca.nome_anexo(ordem, num, p["tipo"]),
                       processo.baixar_como_pdf(page, ctx, p["url"])))
        descr.append(f"{p['tipo']} (SEI nº {num})")

    of_pdf = of_bytes if processo.eh_pdf(of_bytes) else processo.oficio_pdf(page, of["url"])
    log(f"   ofício PDF: {len(of_pdf)} bytes | anexos: {len(anexos)}")

    link = ""
    if publicar:
        link = biblioteca.publicar(g_graph, grupo, of_pdf, anexos, log=log)

    resumo_txt = resumo.resumir(oficio_texto, cfg, anexos=descr or None)

    if url_teams:
        enviar_teams_webhook(url_teams, msg_html(grupo, clientes, prazo, len(anexos),
                                                 link, resumo_txt, ciencias))
        log("   ✓ Teams notificado")

    # registra o prazo (se houver) e PARA o acompanhamento: a Fase 3 se apoia na raia do
    # card do Kanban, e coletivo não tem card — sem isto ela avisaria "prazo sem card"
    # para cada uma das N empresas, todo dia.
    for i in grupo.destinatarios:
        store.marcar_tratado(i, prazo.data_limite if prazo else "",
                             prazo_dias=prazo.dias if prazo else None,
                             prazo_unidade=prazo.unidade if prazo else "",
                             oficio_desc=grupo.oficio_desc)
        if prazo:
            store.parar_acompanhamento(i.chave, MOTIVO_SEM_CARD)

    return {"processo": grupo.processo, "doc_id": grupo.doc_id,
            "empresas": len(grupo.destinatarios), "ciencias": ciencias,
            "prazo": prazo.data_limite if prazo else "", "anexos": len(anexos),
            "pasta": link}


def msg_html(grupo: Grupo, clientes, prazo, n_anexos: int, link: str,
             resumo_txt: str = "", ciencias: int = 0) -> str:
    """Mensagem do Teams. O link da pasta é o item acionável: é de lá que o cliente lê."""
    import html as _html

    def esc(s) -> str:
        return _html.escape(str(s), quote=False)

    urgente = grupo.prioridade_urgente
    titulo = ("Ofício coletivo — ciência dada e documentos publicados" if ciencias
              else "Ofício coletivo — documentos publicados")
    linhas = [
        ("🔴" if urgente else "📌") + f" <b>{titulo}</b>",
        f"<b>Processo:</b> {esc(grupo.processo)}",
        f"<b>Ofício:</b> {esc(grupo.oficio_desc)} ({esc(grupo.doc_id)})",
        f"<b>Tipo:</b> {esc(grupo.tipo_intimacao)}" + (" — ⚠️ <b>URGENTE</b>" if urgente else ""),
        f"<b>Empresas:</b> {len(grupo.destinatarios)}"
        + (f" ({_n_clientes(grupo, clientes)} na base de clientes)" if clientes else ""),
    ]
    if prazo is not None:
        linhas.append(f"⚠️ <b>ATENÇÃO — este coletivo TEM prazo:</b> {esc(prazo.data_limite)} "
                      f"({esc(prazo.tipo)}, {prazo.dias} {esc(prazo.unidade)})")
        linhas.append("👉 Coletivo não entra no acompanhamento automático de prazo — "
                      "controlar à mão.")
    linhas.append(f"<b>Documentos:</b> ofício + {n_anexos} anexo(s)")

    mostradas = grupo.destinatarios[:MAX_EMPRESAS_LISTADAS]
    linhas.append("<b>Destinatários:</b>")
    linhas.extend(f"• {esc(i.destinatario)} — {esc(i.documento_fmt)}" for i in mostradas)
    resto = len(grupo.destinatarios) - len(mostradas)
    if resto > 0:
        linhas.append(f"• (+{resto} empresa(s))")

    corpo = "<br>".join(linhas)
    if resumo_txt:
        corpo += f"<br><br><b>Resumo:</b><br>{esc(resumo_txt)}"
    if link:
        # a URL não passa por escape: escapar o '&' quebraria o link do SharePoint
        corpo += f'<br><br>📁 <a href="{link}">Pasta com o ofício e os anexos</a>'
        corpo += "<br><i>Esta pasta é a compartilhada com os clientes.</i>"
    return corpo


def _n_clientes(grupo: Grupo, clientes) -> int:
    return sum(1 for i in grupo.destinatarios if clientes.info(i.documento) is not None)
