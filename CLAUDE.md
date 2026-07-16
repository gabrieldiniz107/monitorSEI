# monitorSEI — Monitoramento SEI (Anatel) · Jurídico SCM

Bot que monitora o **SEI Acesso Externo da Anatel** na conta única do CEO (Rodrigo,
procurador de todos os provedores), detecta processos/intimações novos e avisa o time
no **Teams**, com o status de cada cliente (SharePoint). É o **Item 1** do plano do
Jurídico da SCM. Contexto amplo do Jurídico está no CLAUDE.md da raiz do projeto pai.

> **Status: FASE 1 EM PRODUÇÃO** (desde 2026-07-16). Roda 4x/dia via cron na VPS.

---

## ⚠️ Regra de ouro

O bot é **estritamente somente-leitura**. **NUNCA** clica na coluna "Ações"/lupa, **nunca**
abre uma intimação "Pendente", **nunca** dá ciência. Abrir/consultar uma intimação Pendente
a converte em "Cumprida por Consulta Direta" e **INICIA O PRAZO** do processo. Toda a Fase 1
só raspa listagens em texto. (A Fase 2 vai dar ciência de propósito, mas só para clientes
individuais ATIVOS e atrás de uma flag separada — ver no fim.)

---

## Como funciona (fluxo de uma execução)

1. **Login autônomo** no Acesso Externo (Playwright/Chromium). Passa pelo **Cloudflare
   Turnstile** (por isso Playwright, não `requests`) e **captura o próprio código 2FA** por
   IMAP (Gmail do Rodrigo, remetente `naoresponder_sei@anatel.gov.br`).
2. Vai para a tela **"Intimações Eletrônicas"** e raspa a **1ª página** (100 mais recentes;
   a lista vem do mais novo p/ o mais antigo).
3. Agrupa por ofício: **coletivo** (mesmo ofício p/ várias empresas) vs **individual** (uma).
4. **Deduplica** contra um SQLite (`state/intimacoes.db`) → só o que é novo passa.
5. **Cross-check no SharePoint** por CNPJ: marca cada empresa como ativo/não-ativo + adimplência.
6. **Notifica no Teams** (HTML) via webhook do Power Automate. Marca como visto.

## Arquitetura (`seibot/`)

| Arquivo | Responsabilidade |
|---|---|
| `config.py` | Carrega o `.env` (dataclass `Config`, `load_config()`). |
| `email_code.py` | Captura o código 2FA via IMAP (`esperar_codigo`). |
| `login.py` | Login Playwright + 2FA → `LoginSession` (tem `.page`). Chromium com `--no-sandbox`. |
| `intimacoes.py` | Raspagem + **parser puro** (`parse_pagina`) + navegação (`coletar`). |
| `models.py` | `Intimacao`, `Grupo` (dataclasses). |
| `classificar.py` | `agrupar_por_oficio` → coletivo vs individual. |
| `store.py` | Dedup SQLite (`IntimacoesStore`: `ja_visto`/`marcar_visto`/`marcar_lote`). |
| `clientes.py` | `SharePointClientes` — cross-check por CNPJ (ver regra de "ativo"). |
| `graph.py` | Cliente Microsoft Graph (app-only) do SharePoint "Gestão Integrada". |
| `notify.py` | `formatar_grupo` (texto, p/ dry-run/testes) e `formatar_grupo_html` (Teams) + envio. |
| `teams.py` | POST no webhook (estilo `text` = `{"text": "..."}`, ou `card`). |
| `monitor.py` | Orquestrador + CLI: `run` / `baseline` / `dry-run`. |
| `validar_login.py` | Valida só o login (usado p/ testar Turnstile headless). |

## Fontes de dados

**SEI — tela "Intimações Eletrônicas"** (`acao=md_pet_intimacao_usu_ext_listar`): colunas
Processo · Documento Principal (`Ofício N (docid)`) · Destinatário (`Razão Social (CNPJ)`) ·
Tipo de Destinatário · Tipo de Intimação (sufixo "URGENTE" = prioridade) · Data de Expedição ·
Situação (Pendente / Cumprida por Consulta Direta / Cumprida por Decurso do Prazo Tácito /
Respondida) · Ações (lupa — **não tocar**). Cada `<tr>` tem `data-idintimacao`/`data-docprinc`;
células por `data-label`. Sem iframe.

**SharePoint "Gestão Integrada"** (`scmprovedor.sharepoint.com/sites/GestaoIntegrada`, via
Graph app-only, app "SCM VISTORIAS", `Sites.ReadWrite.All`; credenciais `GRAPH_*` no `.env`):
- **Clientes SCM** (`Title`=CNPJ formatado, `StatusContrato`, e-mails em
  `field_3`/`EmailFinanceiro`/`EmailTecnico`/`EmailAdm`).
- **Comercial** (`StatusContrato` por contrato; CNPJ é lookup `CNPJLookupId`→id da Clientes SCM).
- **Financeiro** (`Situacao` = adimplência).
- **Regra de "ativo" = UNIÃO**: `StatusContrato=Ativo` na Clientes SCM **OU** ≥1 contrato
  "Ativo" no Comercial. (Cruzamento mostrou o campo da Clientes SCM desatualizado p/ ~132
  clientes com contrato vivo; a união recupera esses.) Join por CNPJ (só dígitos).

## Aprendizados / armadilhas (não regredir)

- **Turnstile** na tela de login → tem que ser navegador real (Playwright). `requests` é barrado.
- **`infra_hash`**: token anti-CSRF por sessão; reusar hash velho → logout. Sempre seguir o
  **link fresco** do DOM logado (`a[href*='md_pet_intimacao_usu_ext_listar']`), nunca URL fixa.
- **Botões/links do SEI são `onclick` JS** → Playwright não consegue "clicar" (timeout). Ou
  chama-se a função global via `evaluate`, ou (adotado) **evita-se** paginação/filtro raspando
  só a 1ª página (o dedup garante o resto — a lista é ordenada do mais novo p/ o mais antigo).
- **`wait_until="commit"` + settle-wait ~2,5s** antes de ler `page.content()` — senão a tabela
  (~200KB) é lida cortada.
- **Teams posta como HTML** → mensagem em `\n` vira "texto corrido". Usar `formatar_grupo_html`
  (`<b>`, `<br>`, `html.escape`).
- **Chromium como root no Docker** exige `--no-sandbox` (já no `login.py`).

## Comandos

```bash
python -m seibot.monitor dry-run    # mostra o que enviaria (sem banco/Teams)
python -m seibot.monitor baseline   # marca os recentes como vistos (1x no deploy)
python -m seibot.monitor run        # detecta novos e notifica no Teams
python validar_login.py             # valida só o login (teste do Turnstile headless)
pytest -q                           # 29 testes (parser/classificar/store/notify/monitor/clientes)
```

Parser e classificador são **puros** (testáveis sem browser). A fixture real
(`tests/fixtures/intimacoes_page.html`) tem dados reais e **não é versionada**; os testes que
dependem dela pulam quando ausente (num clone limpo).

## Deploy (produção)

Roda na VPS `SCMengenharia` (mesma do scm-watchers), em **`/opt/monitorSEI`**, via Docker.
Execução **efêmera** (não é daemon — não aparece no `docker ps` fora dos ~1-2 min de execução).

- `Dockerfile` (imagem `mcr.microsoft.com/playwright/python:v1.48.0-jammy`) + `docker-compose.yml`
  (volume `./state:/app/state`, `env_file: .env`, `restart: "no"`).
- **Turnstile headless PASSOU na VPS** (não precisou de xvfb).
- Cron do root (`crontab -l`):
  ```cron
  CRON_TZ=America/Sao_Paulo
  0 7,11,14,17 * * * cd /opt/monitorSEI && docker compose run --rm sei-monitor python -m seibot.monitor run >> /var/log/sei-monitor.log 2>&1
  ```
- Logs em `/var/log/sei-monitor.log`. Cada run imprime JSON: `{"status","coletados","novos","notificados"}`.
- **Segredos**: só no `.env` (gitignored — não versionar). `.env.example` tem o esqueleto.
  Deploy do `.env`: `scp` do `.env` local para a VPS + `HEADLESS=true`.
- Passo a passo completo: `DEPLOY.md`. Webhook do Teams: `WEBHOOK.md`.

## Pontos abertos / a melhorar

- **Qualidade de dados**: algumas empresas que recebem intimação (ex. IMPACTO, WAY.COM)
  constam "não-ativo (sem status)" — provável lacuna de cadastro na Clientes SCM/Comercial.
- **Paginação do Graph** foi endurecida (retry + sem header `MayFailRandomly` em listagem);
  se voltar a variar a contagem de clientes, revisar.
- Cobertura do `run`: raspa só a 1ª página (100). Se em 6h chegarem >100 intimações novas,
  o excedente não é visto (há um aviso no log). Improvável, mas monitorar.

---

## PRÓXIMO PASSO — Fase 2: tratativa individual (clientes ATIVOS)

Objetivo: para cada intimação **nova, individual e de cliente ATIVO**, agir automaticamente.
Individual **não-ativo/fora da base** → continua só notificando o Jurídico com o motivo (já feito).

**⚠️ Esta fase DÁ CIÊNCIA (inicia o prazo). Salvaguardas obrigatórias:**
- Só para **individual + ativo** (a decisão já é calculada em `notify._decisao_individual`).
- **Atrás de um comando/flag separado** (ex.: `monitor tratar` ou `run --tratar`) — **nunca**
  no `run` padrão de produção, para não ligar ciência por acidente.
- `dry-run` da tratativa (mostra o que faria, sem abrir/enviar) antes de ligar em prod.

**Passo a passo técnico:**
1. Filtrar as intimações novas que são individual + cliente ativo.
2. Abrir a intimação/processo (`processo_acesso_externo_consulta.php`) → **dá ciência**.
3. Ler a **data de vencimento** do prazo (só existe após a ciência).
4. Baixar o **PDF do ofício** (documento principal) e os **anexos**.
5. Gerar um **resumo** do ofício + anexos (definir: LLM qual/prompt, ou template).
6. Buscar os **e-mails do cliente** no SharePoint (`clientes.emails(cnpj)` — já implementado).
7. Enviar **e-mail pelo Jurídico** ao cliente com resumo + anexos.
8. Registrar o que foi feito (evitar re-tratar → estender o `store` com flag "tratado";
   e/ou lista Jurídico no SharePoint) e notificar o time.

### Decisões travadas (2026-07-16)
- **Ciência automática** na Etapa 1 (o bot abre e dá ciência sozinho p/ individual ativo).
- **Envio de e-mail em 2 etapas:** Etapa 1 = **criar rascunho + notificar o Teams p/ validação**
  (humano envia); Etapa 2 (depois) = envio direto via **fluxo Power Automate**.
- **Remetente do Jurídico:** `juridico@scmengenharia.com.br`.
- **Resumo:** LLM **OpenAI** (reaproveitar a chave do projeto de vistorias).
- **Tudo reportado no Teams** (processo, o que foi feito, prazo, para quem foi o e-mail).

### Achados da exploração (usando processos JÁ CUMPRIDOS — regra: só abrir Situação != Pendente)
- **Página do processo** = `processo_acesso_externo_consulta.php?id_acesso_externo=<ID>&infra_hash=<sessão>`
  (título "Acesso Externo com Disponibilização Parcial de Documentos"). Tem cabeçalho
  (Processo, Tipo, Interessados), botões **Gerar PDF / Gerar ZIP / Peticionamento Intercorrente**,
  e a **Lista de Protocolos** (documentos).
- **Documentos**: cada linha tem link `documento_consulta_externa.php?id_acesso_externo=X&id_documento=Y&infra_hash=Z`
  (`target=_blank`). O **ofício** é o doc cujo Tipo = "Ofício NNN"; **anexos** = demais docs
  que **não** são "Certidão de Intimação Cumprida"; as **certidões** são a prova da ciência.
  Baixar: por documento (essa URL) ou selecionar checkboxes → **Gerar ZIP**.
- **Ícones de Ação** da linha do ofício são **lazy (JS)** — carregam após ~a página renderizar.
  Num processo **já cumprido**: ícone "doc principal" (tooltip **"Cumprida em: DD/MM/AAAA"** =
  data da ciência) + ícone "certidão". **O ícone azul de "Resposta" com o PRAZO NÃO aparece
  em cumprido — é exclusivo de intimação PENDENTE.** Logo, a tela de Resposta/prazo só será
  mapeada no **1º pendente real** (com cuidado).
- **Estratégia do prazo/vencimento:** primário = tela **Resposta** (ícone azul, mapear no 1º
  pendente); **fallback** = data da ciência ("Cumprida em") + prazo em dias extraído do **texto
  do ofício** pelo LLM. Vencimento = ciência + prazo.
- Fixtures reais (`processo_detalhe.*`, `oficio_doc.*`) são gitignored.

### Progresso (branch `fase-2-tratativa-individual`)
- ✅ **Increment 1**: `seibot/tratativa.py` (`selecionar_candidatos` — individual + ativo +
  Pendente, puro/testável) + comando **`monitor tratar`** em **MODO ENSAIO** (só lista os
  candidatos, NÃO abre nada). 6 testes (`test_tratativa.py`). 35 testes no total.
- ⬜ Increment 2: módulo de resumo (OpenAI), testável isolado.
- ⬜ Increment 3: abrir + capturar prazo + baixar ofício/anexos (testar no 1º pendente real).
- ⬜ Increment 4: criar rascunho + notificação completa no Teams + registro "tratado".

**Ainda a fechar com o usuário:** template do e-mail; onde registrar o histórico de tratados
(store com flag "tratado" e/ou lista Jurídico no SharePoint); a chave OpenAI (de onde vem).
