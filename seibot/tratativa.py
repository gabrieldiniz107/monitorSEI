"""Fase 2 — seleção de candidatos à tratativa individual.

Um candidato é um grupo **individual** (um ofício para uma empresa), cujo cliente é
**ATIVO** (SharePoint) e cuja Situação é **Pendente** (ainda sem ciência). Só esses
seguem para a tratativa (abrir → ciência → prazo → ofício/anexos → resumo → e-mail).

⚠️ Esta seleção é PURA (não abre nada). Abrir/dar ciência é responsabilidade do
executor da tratativa, atrás de comando/flag separado — nunca no `run` de produção.
"""
from __future__ import annotations

import re
from typing import Optional

from .clientes import BaseClientes, motivo_sem_tratativa
from .models import Grupo, Intimacao

SITUACAO_PENDENTE = "Pendente"
# Situações em que a ciência JÁ foi dada (por humano ou pelo bot) e o prazo já corre.
# "Respondida" fica de fora: o cliente já respondeu, não há o que encaminhar.
SITUACOES_CIENCIA_DADA = frozenset({
    "Cumprida por Consulta Direta",
    "Cumprida por Decurso do Prazo Tácito",
})


class TratativaIncompleta(RuntimeError):
    """Falha DEPOIS que a ciência já foi dada.

    Estado perigoso: o prazo legal já está correndo, o checkpoint no store impede o retry
    automático, e o cliente ainda NÃO recebeu o rascunho. Exige ação humana — por isso o
    chamador notifica como CRÍTICO.
    """

    def __init__(self, msg: str, *, processo: str, empresa: str, prazo: str = ""):
        super().__init__(msg)
        self.processo, self.empresa, self.prazo = processo, empresa, prazo


def _nome_arquivo(base: str, num: str) -> str:
    s = re.sub(r"[^\w]+", "_", f"{base}_{num}", flags=re.U).strip("_")
    return (s or f"doc_{num}") + ".pdf"


def _msg_tratativa_html(grupo: Grupo, intim: Intimacao, prazo, emails, n_anexos, criou,
                        card_criado: bool = False) -> str:
    linhas = [
        "📌 <b>Tratativa individual — SEI</b>",
        f"<b>Processo:</b> {grupo.processo}",
        f"<b>Ofício:</b> {grupo.oficio_desc} ({grupo.doc_id})",
        f"<b>Empresa:</b> {intim.destinatario} — {intim.documento_fmt}",
        f"<b>Tipo:</b> {grupo.tipo_intimacao}",
    ]
    if prazo is not None:
        linhas.append(f"<b>Prazo:</b> {prazo.data_limite} ({prazo.tipo}, {prazo.dias} {prazo.unidade})")
    else:
        linhas.append("<b>Prazo:</b> — (sem prazo de resposta)")
    linhas.append(f"<b>Documentos:</b> ofício + {n_anexos} anexo(s)")
    if criou:
        linhas.append(f"✅ <b>Rascunho criado</b> na caixa do Jurídico para: "
                      + (", ".join(emails) if emails else "(sem e-mails cadastrados!)"))
        linhas.append("👉 Revisar e enviar.")
    else:
        linhas.append("🧪 (ensaio — rascunho NÃO criado)")
    if card_criado:
        linhas.append("🗂️ <b>Card criado</b> no Controle de Ofício (Jurídico).")
    return "<br>".join(linhas)


def _comentar_automacao(cfg, card_id: str, grupo: Grupo, log) -> None:
    """Comenta no card que ele foi gerado pela automação (padrão CREA/CFT). Cosmético e
    best-effort: se falhar (sem login delegado, token expirado…), só loga — o card já existe.
    Usa SharePoint REST com auth delegada (o mesmo login device-code do teams_dm)."""
    try:
        from . import comentarios, oficio_card
        comentarios.postar_comentario(cfg, oficio_card.LISTA_CONTROLE_OFICIO, card_id,
                                      comentarios.texto_card(grupo))
        log("   ✓ comentário de automação postado no card")
    except Exception as e:  # noqa: BLE001 — comentário é só proveniência; não é crítico
        log(f"   ⚠️ card criado, mas falhou o comentário de automação: {e}")


def _criar_card_best_effort(cfg, clientes, grupo, intim, prazo, log) -> Optional[str]:
    """Cria o card do ofício no SharePoint. **Best-effort**: qualquer falha aqui NÃO derruba
    a tratativa (ciência + rascunho já concluídos) — só loga e avisa o responsável técnico.

    Precisa de um cliente Graph que ESCREVA; só a SharePointClientes expõe `.graph`. Sem ele
    (ex.: fake nos testes, ou Fase 1 sem SharePoint) simplesmente não cria card."""
    from datetime import date

    g = getattr(clientes, "graph", None)
    if g is None:
        return None
    try:
        from . import oficio_card
        info = clientes.info(intim.documento) if clientes else None
        cid = oficio_card.criar_card(g, grupo, intim, prazo, info,
                                     data_cumprimento=date.today(), log=log)
        if cid:
            _comentar_automacao(cfg, cid, grupo, log)
        return cid
    except Exception as e:  # noqa: BLE001 — card é registro de gestão, não pode quebrar a tratativa
        log(f"   ⚠️ falha ao criar card no Controle de Ofício: {e}")
        from .erros import notificar_erro
        notificar_erro(cfg, f"card ofício · {grupo.processo}", e,
                       detalhe=(f"<b>Empresa:</b> {intim.destinatario}<br>"
                                "Ciência e rascunho OK; só o card no SharePoint falhou. "
                                "Criar/conferir à mão se necessário."))
        return None


def tratar_um(sess, cfg, grupo: Grupo, clientes: Optional[BaseClientes], store, *,
              criar_rascunho: bool = False, dar_ciencia: bool = False,
              url_teams: Optional[str] = None, log=print) -> dict:
    """Trata UM candidato: abre o processo → [ciência] → prazo → baixa ofício+anexos →
    resumo → monta e-mail → (opcional) cria rascunho → notifica Teams → marca 'tratado'.

    ⚠️ `dar_ciencia=True` INICIA O PRAZO (irreversível). Abrir o processo, por si só, não dá
    ciência — mas sem ela a Lista de Protocolos vem vazia e o prazo não existe, então uma
    intimação Pendente SÓ pode ser tratada com `dar_ciencia=True`.
    """
    from . import processo, rascunho, resumo
    from .teams import enviar_teams_webhook

    intim = grupo.destinatarios[0]
    page, ctx = sess.page, sess.context
    log(f"→ Tratando {grupo.processo} | {intim.destinatario} | {grupo.oficio_desc}")

    processo.abrir_processo(page, intim.consulta_url)

    ciencia_dada = False
    aceites = processo.urls_aceite(page)
    # os ícones de aceite são a ÚNICA fonte de "quais documentos são desta intimação" — e
    # somem depois da ciência. Capturar aqui, antes, senão só resta a Lista de Protocolos
    # (que é o processo inteiro, com documentos internos da Anatel).
    docs_intimacao = [a["num"] for a in aceites if a.get("num")]
    if aceites:
        if not dar_ciencia:
            raise RuntimeError(
                f"intimação {grupo.doc_id} ainda PENDENTE (aceite não dado) e dar_ciencia=False "
                "— sem ciência não há Lista de Protocolos nem prazo. Abortado sem tocar nela.")
        alvo = processo.escolher_aceite(aceites, grupo.doc_id)
        log(f"   ⚠️ DANDO CIÊNCIA (doc {alvo['num']}) — inicia o prazo…")
        try:
            processo.dar_ciencia(page, alvo["url"])
        except processo.CienciaIncerta as e:
            # assume que saiu: sem o checkpoint o prazo correria com o registro perdido.
            store.marcar_tratado(intim, "")
            raise TratativaIncompleta(str(e), processo=grupo.processo,
                                      empresa=intim.destinatario) from e
        ciencia_dada = True
        store.marcar_tratado(intim, "")   # checkpoint: ciência dada, prazo já corre
        processo.abrir_processo(page, intim.consulta_url)  # recarrega já com os links vivos
        log("   ✓ ciência confirmada")
    else:
        # Sem ícone de aceite = a ciência já foi dada (tipicamente por alguém do Jurídico
        # que abriu a intimação no SEI antes do cron das 07:10). O prazo já corre, então
        # seguimos com o resto — é o único jeito de o cliente receber o ofício.
        log("   • sem ícone de aceite: ciência já dada fora do bot — seguindo sem dar ciência")

    try:
        return _tratar_apos_ciencia(sess, cfg, grupo, intim, clientes, store,
                                    criar_rascunho=criar_rascunho, url_teams=url_teams,
                                    docs_intimacao=docs_intimacao, log=log)
    except Exception as e:
        if not ciencia_dada:
            raise
        # ciência já dada: o prazo corre, o checkpoint bloqueia retry e o cliente não foi
        # avisado. Vira erro CRÍTICO para alguém agir à mão.
        raise TratativaIncompleta(str(e), processo=grupo.processo,
                                  empresa=intim.destinatario) from e


def _tratar_apos_ciencia(sess, cfg, grupo: Grupo, intim: Intimacao,
                         clientes: Optional[BaseClientes], store, *,
                         criar_rascunho: bool, url_teams: Optional[str],
                         docs_intimacao: Optional[list] = None, log=print) -> dict:
    """Da Lista de Protocolos até o rascunho. Separado para que qualquer falha aqui seja
    classificada como pós-ciência pelo `tratar_um`."""
    from . import processo, rascunho, resumo
    from .teams import enviar_teams_webhook

    page, ctx = sess.page, sess.context
    protos = processo.mapa_protocolos(page)
    if not protos:
        raise RuntimeError("Lista de Protocolos vazia mesmo após a ciência — abortado.")
    resp_url = processo.url_peticionar_resposta(page)
    prazo = processo.capturar_prazo(page, resp_url) if resp_url else None
    log(f"   prazo: {prazo.data_limite if prazo else '—'}")

    of = protos.get(grupo.doc_id)
    if not of:
        raise RuntimeError(f"ofício {grupo.doc_id} não achado na Lista de Protocolos")
    of_bytes = processo.baixar(ctx, of["url"])
    # ofício gerado no SEI = HTML; Notificação de Lançamento & afins = PDF de verdade. Extrair
    # o texto pelo conteúdo (senão o resumo LLM recebe binário) — ver processo.extrair_texto_oficio.
    oficio_texto = processo.extrair_texto_oficio(of_bytes)

    # anexos: só os documentos DA INTIMAÇÃO (ícones de aceite), nunca o processo inteiro
    citados = processo.extrair_anexos(oficio_texto)
    if not docs_intimacao:
        log("   ⚠️ sem ícones de aceite (processo já cumprido) — anexos vêm só dos "
            "'(SEI nº …)' citados no texto do ofício.")
    anexos_nums = processo.anexos_da_intimacao(
        protos, grupo.doc_id, docs_intimacao, citados)
    anexos: list[tuple[str, bytes]] = []
    descr_anexos: list[str] = []
    for num in anexos_nums:
        p = protos.get(num)
        if p:
            # baixar_como_pdf (não baixar cru): documentos gerados no SEI (Despacho, Informe…)
            # vêm em HTML — salvá-los como .pdf gera arquivo que não abre. Ver processo.py.
            anexos.append((_nome_arquivo(p["tipo"], num),
                           processo.baixar_como_pdf(page, ctx, p["url"])))
            descr_anexos.append(f"{p['tipo']} (SEI nº {num})")

    # se o ofício já é PDF, anexa os bytes crus; se é HTML gerado no SEI, renderiza via Chromium.
    of_pdf = of_bytes if processo.eh_pdf(of_bytes) else processo.oficio_pdf(page, of["url"])
    log(f"   ofício PDF: {len(of_pdf)} bytes | anexos: {len(anexos)}")

    resumo_txt = resumo.resumir(oficio_texto, cfg, anexos=descr_anexos or None)
    emails = clientes.emails(intim.documento) if clientes else []
    assunto = rascunho.montar_assunto(grupo.oficio_desc, grupo.doc_id, grupo.processo)
    corpo = rascunho.montar_corpo_html(intim.destinatario, grupo.processo, grupo.oficio_desc,
                                       grupo.doc_id, resumo_txt, prazo, tem_anexos=bool(anexos))
    todos = [(_nome_arquivo("Oficio", grupo.doc_id), of_pdf)] + anexos
    msg = rascunho.montar_mensagem_graph(emails, assunto, corpo, todos)

    if criar_rascunho:
        if not cfg.powerautomate_rascunho_url:
            raise RuntimeError("POWERAUTOMATE_RASCUNHO_URL não configurado no .env")
        if not emails:
            log("   ⚠️ cliente sem e-mails cadastrados — criando rascunho sem destinatário.")
        rascunho.criar_rascunho(cfg.powerautomate_rascunho_url, msg)
        log("   ✓ rascunho criado na caixa do Jurídico")

    # Card no Kanban do Jurídico (ControleOficioJuridico) — ao final da tratativa. Best-effort:
    # falha aqui não é crítica (a ciência e o rascunho já foram concluídos acima).
    card_id = _criar_card_best_effort(cfg, clientes, grupo, intim, prazo, log) if criar_rascunho else None

    if url_teams:
        enviar_teams_webhook(
            url_teams,
            _msg_tratativa_html(grupo, intim, prazo, emails, len(anexos), criar_rascunho,
                                card_criado=bool(card_id)),
            "text")

    # grava o prazo completo (dias + unidade): dia útil ≠ dia corrido, e a cadência de
    # avisos de vencimento vai depender dos dois.
    store.marcar_tratado(intim, prazo.data_limite if prazo else "",
                         prazo_dias=prazo.dias if prazo else None,
                         prazo_unidade=prazo.unidade if prazo else "",
                         oficio_desc=grupo.oficio_desc)
    return {"processo": grupo.processo, "empresa": intim.destinatario,
            "prazo": prazo.data_limite if prazo else None,
            "emails": emails, "anexos": len(anexos), "rascunho": criar_rascunho,
            "card": card_id}


def motivo_nao_candidato(g: Grupo, clientes: Optional[BaseClientes], *,
                         promessa_aberta: bool = False) -> Optional[str]:
    """Por que este grupo NÃO deve ser tratado. `None` = pode tratar.

    Espelha `clientes.motivo_sem_tratativa`: devolve texto pronto para o Teams, para que
    o descarte deixe de ser silencioso. Antes isto era um `eh_candidato` booleano, e uma
    intimação prometida podia sumir da seleção sem nenhum registro do porquê — foi o que
    aconteceu com a Age Telecomunicações em 05/08/2026 (Ofício 688).
    """
    if g.tipo != "individual":
        return f"o ofício virou coletivo ({len(g.destinatarios)} destinatários)"
    intim = g.destinatarios[0]
    if intim.situacao != SITUACAO_PENDENTE:
        # Ciência já dada. Se o bot havia prometido tratar, ele segue mesmo assim: o passo
        # irreversível ficou para trás e o cliente continua precisando do ofício e do prazo
        # (decisão do usuário, 2026-08-05). Sem promessa aberta, NÃO — senão o próximo
        # `--modo real` trataria todo o histórico cumprido da janela de 100 linhas de uma
        # vez, enviando dezenas de rascunhos a clientes.
        if not (promessa_aberta and intim.situacao in SITUACOES_CIENCIA_DADA):
            return f"situação mudou para '{intim.situacao}'"
    if clientes is None:
        return "sem base de clientes para decidir (SharePoint indisponível)"
    # mesma regra do aviso ao Jurídico (notify): ativo E não-inadimplente
    return motivo_sem_tratativa(clientes.info(intim.documento))


def eh_candidato(g: Grupo, clientes: Optional[BaseClientes], *,
                 promessa_aberta: bool = False) -> bool:
    return motivo_nao_candidato(g, clientes, promessa_aberta=promessa_aberta) is None


def selecionar_candidatos(grupos: list[Grupo], clientes: Optional[BaseClientes],
                          prometidas: "set[str] | None" = None) -> list[Grupo]:
    """Grupos individuais + cliente ATIVO e NÃO-INADIMPLENTE, com Situação Pendente —
    ou já com ciência dada, se estiver entre as `prometidas` (chaves de promessa aberta).

    Inadimplente ativo fica de fora de propósito (decisão 2026-07-21): o bot não abre nem
    dá ciência — o Jurídico é avisado pelo `run` com o motivo e trata à mão.
    """
    prometidas = prometidas or set()
    return [g for g in grupos
            if eh_candidato(g, clientes,
                            promessa_aberta=g.destinatarios[0].chave in prometidas)]
