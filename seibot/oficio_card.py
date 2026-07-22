"""Fase 2 — cria o card do ofício no Kanban do Jurídico (lista ControleOficioJuridico).

Ao final da tratativa individual, registra o processo na lista **"Jurídico - Controle de
Ofício"** (site Gestão Integrada) com os dados factuais que já temos em mãos.

**Decisão do usuário (2026-07-22):** os campos de **workflow/juízo** ficam EM BRANCO de
propósito — o time do Jurídico os edita conforme conduz o caso:
- `StatusOficio` (as raias do Kanban), `TipoOficio`
- `LoginSEI` / `SenhaSEI` (usamos o login único do Rodrigo, não o do cliente)
- todo o bloco AGU (`PrazoAGUdias`, `DataInicioAGU`, …); `DataAGUfim` é coluna CALCULADA da
  lista (read-only) — o bot não a toca; ela mostra 30/12/1899 quando o AGU não começou.

Preenchemos o que é objetivo da intimação/cliente: nº do processo, nº do ofício, CNPJ (lookup
+ só-dígitos), datas de cumprimento e vencimento, contatos, **Prioridade** (URGENTE→Alta,
senão Média) e **Pacote** (tier do contrato ativo — ver `clientes._melhor_pacote`).

`CNPJ` é um **lookup** para a lista Clientes SCM → grava-se `CNPJLookupId` = o id do cliente
lá (que `clientes.ClienteInfo.sp_item_id` já traz). Confirmado ao vivo (2026-07-22): o item
3539 da Clientes SCM = CNPJ 26.296.963/0001-78, batendo com o card existente.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

# lista "Jurídico - Controle de Ofício" (site Gestão Integrada), descoberta via g.listas()
LISTA_CONTROLE_OFICIO = "407dc958-8ac3-4224-9026-d0759149a235"


def _iso_meia_noite(d: date) -> str:
    """00:00 em Brasília (UTC-3) → '...T03:00:00Z', no mesmo formato dos itens já na lista."""
    return f"{d.isoformat()}T03:00:00Z"


def _iso_de_ddmmaaaa(s: str) -> Optional[str]:
    """'04/08/2026' → '2026-08-04T03:00:00Z'. None se não parsear."""
    try:
        dd, mm, aaaa = (s or "").split("/")
        return _iso_meia_noite(date(int(aaaa), int(mm), int(dd)))
    except Exception:
        return None


def montar_campos(grupo, intim, prazo, info, *, data_cumprimento: date) -> dict:
    """Monta o dict de `fields` do card (puro/testável).

    Só campos objetivos — os de workflow ficam de fora (o Jurídico preenche). Chaves opcionais
    (lookup, vencimento, contatos) só entram quando há dado, para não gravar vazio por cima.
    """
    campos = {
        "Title": grupo.processo,                                   # Nº do Processo
        "NumeroOficio": f"{grupo.oficio_desc} ({grupo.doc_id})",   # ex. "Ofício 407 (15843941)"
        "CNPJsemFormatacao": intim.documento,                      # CNPJ só dígitos
        "DataCumprimento": _iso_meia_noite(data_cumprimento),      # dia da ciência
        # URGENTE (sufixo do Tipo de Intimação no SEI) → Alta; demais → Média. É triagem
        # inicial objetiva; o Jurídico reclassifica se quiser.
        "Prioridade": "Alta" if intim.prioridade_urgente else "Média",
    }
    if info is not None and info.sp_item_id:
        campos["CNPJLookupId"] = info.sp_item_id                   # lookup → Clientes SCM
    if info is not None and info.pacote:
        # Pacote é multi-choice → lista + a anotação @odata.type (o Graph rejeita coleção sem ela)
        campos["Pacote@odata.type"] = "Collection(Edm.String)"
        campos["Pacote"] = [info.pacote]
    if prazo is not None and prazo.data_limite:
        iso = _iso_de_ddmmaaaa(prazo.data_limite)
        if iso:
            campos["DataVencimento"] = iso
    emails = list(info.emails) if info else []
    if emails:
        campos["Email"] = ",".join(emails)
    telefones = list(info.telefones) if info else []
    if telefones:
        campos["Telefone"] = " / ".join(telefones)
    return campos


def criar_card(g, grupo, intim, prazo, info, *, data_cumprimento: Optional[date] = None,
               log=print) -> Optional[str]:
    """Cria o card na lista, **idempotente por Nº do Processo** (não duplica se já existe).

    Devolve o id do item criado, ou `None` se já existia. Levanta em erro de rede/Graph —
    o chamador (tratativa) trata como best-effort (o card é registro de gestão; a ciência e
    o rascunho, que são o que importa, já foram concluídos antes daqui).
    """
    data_cumprimento = data_cumprimento or date.today()
    existente = g.buscar_item(LISTA_CONTROLE_OFICIO, grupo.processo)
    if existente is not None:
        log(f"   • card já existe p/ {grupo.processo} (id {existente.get('id')}) — não duplica.")
        return None
    campos = montar_campos(grupo, intim, prazo, info, data_cumprimento=data_cumprimento)
    novo = g.criar_item(LISTA_CONTROLE_OFICIO, campos)
    cid = str(novo.get("id") or "")
    log(f"   ✓ card criado no Controle de Ofício (id {cid})")
    return cid
