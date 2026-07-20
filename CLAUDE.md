# monitorSEI — Monitoramento SEI (Anatel) · Jurídico SCM

Bot que monitora o **SEI Acesso Externo da Anatel** na conta única do CEO (Rodrigo,
procurador de todos os provedores), detecta processos/intimações novos e avisa o time
no **Teams**, com o status de cada cliente (SharePoint). É o **Item 1** do plano do
Jurídico da SCM. Contexto amplo do Jurídico está no CLAUDE.md da raiz do projeto pai.

> **Status: FASE 1 EM PRODUÇÃO** (desde 2026-07-16). Roda 4x/dia via cron na VPS.

---

## ⚠️ Regra de ouro

Na **Fase 1** o bot é **estritamente somente-leitura**: só raspa listagens em texto, nunca
dá ciência. A **Fase 2** dá ciência de propósito, mas só para individual + cliente ATIVO e
atrás de um comando separado (`tratar --modo real`) — nunca no `run` de produção.

**CORREÇÃO IMPORTANTE (2026-07-20, validado numa intimação Pendente real):** durante muito
tempo assumimos que *abrir* o processo já dava ciência. **Não dá.** Abrir
`processo_acesso_externo_consulta.php` é seguro: mostra só cabeçalho, Lista de Protocolos
(números/tipos) e Andamentos, com os links dos documentos inertes
(`alert('Sem acesso ao documento.')`). **A ciência é um passo discreto e explícito** — o
modal `md_pet_intimacao_usu_ext_confirmar_aceite` + botão `#sbmAceitarIntimacao`. Só esse
clique inicia o prazo. (A lupa da tela de Intimações também só *abre* o processo — ela não
dá ciência sozinha.)

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

### Mecânica da tratativa — VALIDADA ao vivo (2026-07-16, em processos já cumpridos)
- **Reaproveitamento de sessão** (`seibot/sessao.py`): `abrir(cfg, permitir_login)` reusa os
  cookies salvos enquanto a sessão do SEI está viva (evita 2FA a cada passo). Só p/ dev/
  multi-passos; produção continua com login novo por execução. (SEI expira a sessão rápido,
  ~poucos min; o reuso cross-processo raramente pega — o ganho é 1 login por script.)
- **Prazo/vencimento**: na linha do ofício, o ícone `intimacao_peticionar_resposta` (só existe
  se a intimação exige resposta e ainda não foi respondida — some no "mero Conhecimento") leva
  via `window.location` à página `acao=md_pet_responder_intimacao_usu_ext`. Lá, o `<select>`
  **`#selTipoResposta`** tem a opção `"<Tipo> (<N> Dias) - Data Limite: DD/MM/AAAA"`
  (ex. real Goncalves: **"Defesa Preliminar (15 Dias) - Data Limite: 30/07/2026"**). É um
  FORMULÁRIO de peticionamento — **só ler o select, nunca preencher/enviar**.
- **Ofício**: `documento_consulta_externa.php?...&id_documento=X` → HTML (ISO-8859-1); é o texto
  p/ o resumo.
- **Anexos**: citados NO TEXTO do ofício como `"(SEI nº NNNNNN)"` (com entidades HTML:
  `&ordm;`/`&nbsp;` → precisa `html.unescape`). Casam com o nº visível na Lista de Protocolos;
  baixa-se o **PDF** via `context.request.get(url).body()` (validado: Ata 460KB, Manual 231KB).
  Ofício sem `(SEI nº …)` ⇒ sem anexos.

### Progresso (branch `fase-2-tratativa-individual`)
- ✅ **Increment 1**: `seibot/tratativa.py` (`selecionar_candidatos`) + comando `monitor tratar`
  em MODO ENSAIO (só lista, não abre). `test_tratativa.py`.
- ✅ **Sessão**: `seibot/sessao.py` (reaproveitamento).
- ✅ **Increment 3 (core)**: `seibot/processo.py` — parsers puros `extrair_anexos` e
  `parse_prazo` (testados em texto real) + helpers `abrir_processo`, `mapa_protocolos`,
  `baixar`, `url_peticionar_resposta`, `capturar_prazo`. `test_processo.py`. **41 testes.**
- ✅ **Increment 2**: `seibot/resumo.py` — `resumir(oficio_texto, cfg, anexos, client)` via
  OpenAI (`gpt-4o-mini`), cliente injetável (testes com fake). `limpar()` HTML→texto.
  `test_resumo.py`. **44 testes.** Validado ao vivo com o Ofício 498 real (resumo preciso).
- ✅ **Increment 4 (construído + ensaio-geral validado)**: orquestração `tratativa.tratar_um`
  (abrir processo → capturar prazo → baixar ofício + anexos → PDF do ofício via `page.pdf()`
  [só headless] → resumo LLM → montar e-mail → **criar rascunho** no Jurídico via Power Automate
  → notificar Teams → marcar "tratado"). `seibot/rascunho.py` (montar assunto/corpo/mensagem
  Graph + `criar_rascunho`), `store` ganhou tabela `tratadas`, `models`/`intimacoes` ganharam
  `consulta_url`/`id_acesso_externo`. Comando **`monitor tratar --modo {ensaio|completo|real}`**:
  - `ensaio` (default) = só lista candidatos; `completo --processo <nº>` = ensaio-geral num
    processo **já cumprido** (roda tudo e cria rascunho de verdade, SEM ciência); `real` = dá
    **ciência** de verdade (só pendentes; nunca no `run` de produção).
  - **Ensaio-geral validado ao vivo (2026-07-16)** no Goncalves (cumprido): prazo 30/07/2026,
    ofício PDF 163 KB, 2 anexos, rascunho criado no `juridico@` com os 4 e-mails da empresa,
    Teams notificado. **51 testes.** POWERAUTOMATE_RASCUNHO_URL no `.env`.

### ✅ Mapeamento do PENDENTE real — feito (2026-07-20)

Primeira intimação individual+ativa+Pendente: **proc `53508.003179/2026-50`, Ofício 70
(15981104), Cabos Brasil Europa Ltda**, Requerimento de Informações, expedida 20/07/2026,
processo "Fiscalização: Segurança Cibernética", nível **Sigiloso**. Mapeada e tratada
ponta a ponta. O que se aprendeu:

**1. Abrir o processo NÃO dá ciência** (ver Regra de Ouro). Antes do aceite:
`mapa_protocolos()` volta **vazio** (links inertes) e `url_peticionar_resposta()` volta
**None** — ou seja, **o prazo não é legível antes da ciência**.

**2. A tela de consentimento.** Na linha de cada documento da intimação há um ícone
`intimacao_nao_cumprida_doc_principal|doc_anexo.svg` com
`onclick="infraAbrirJanelaModal('…acao=md_pet_intimacao_usu_ext_confirmar_aceite
&id_acesso_externo=…&id_documento=…&id_intimacao[]=…&infra_hash=…', 900, 470)"`.
A tela explica o aceite e traz **`#sbmAceitarIntimacao`** ("Confirmar Consulta à Intimação")
e `#sbmFechar`. Confirmar **um** documento cumpre a intimação inteira (mesmo `id_intimacao[]`).
Texto útil: *"considerar-se-á cumprida a intimação com a presente consulta … ou, não efetuada
a consulta, em 10 dias após a data de sua expedição"* — o decurso tácito aparece explícito
(aqui, 30/07/2026). Nenhum diálogo JS nativo é usado.

**3. Depois da ciência** tudo destrava: os links viram `documento_consulta_externa.php`,
nasce a **"Certidão de Intimação Cumprida"** na Lista de Protocolos e aparece o ícone de
resposta (a URL ganha um `id_aceite[]=…` novo). O `#selTipoResposta` traz o prazo no **mesmo
formato** do já-cumprido → `parse_prazo` não precisou mudar:
`"Resposta a Requerimento de Informações (15 Dias) - Data Limite: 04/08/2026"`.
(Dar ciência hoje moveu o prazo de 30/07 tácito p/ **04/08/2026**.)

**4. Anexos NÃO saem do texto do ofício.** O Ofício 70 citava `(SEI nº …)` de **1 dos 2**
anexos → o 1º rascunho foi criado sem a Planilha de Maturidade. Corrigido: a fonte primária
agora é a **Lista de Protocolos** (`processo.anexos_de_protocolos`) = tudo que não é o ofício
nem a Certidão de Intimação Cumprida. `extrair_anexos` (texto) virou secundário, só ordena.

**Mudanças de código daí (2026-07-20):** `processo.urls_aceite()` e `processo.dar_ciencia()`;
`processo.anexos_de_protocolos()`; `tratativa.tratar_um` ganhou `dar_ciencia: bool` e a ordem
correta (**abrir → ciência → reabrir → protocolos → prazo → downloads**), com **checkpoint**
`store.marcar_tratado` logo após a ciência (se o pipeline quebrar depois, o prazo já corre e
o registro não se perde) e **salvaguarda**: se houver ícone de aceite e `dar_ciencia=False`,
aborta sem tocar em nada. `ensaio`/`completo` passam `dar_ciencia=False`; só `real` passa True.
**57 testes.**

### ⚠️ Ainda NÃO está pronto para produção
- Faltam **ajustes de texto/tom do e-mail** ao cliente (template em `rascunho.py` — a definir).
- O **`tratar --modo real`** (que dá ciência sozinho, sem `--processo`) ainda não foi rodado
  ponta a ponta: no pendente real fizemos a ciência por script de mapeamento e depois o
  pipeline via `--modo completo`. O caminho está construído e testado, mas o comando em si
  espera o próximo pendente.
- **Nada agenda a Fase 2**: o cron da VPS só roda `run`. Falta decidir cadência do `tratar`.
- Cliente Cabos Brasil Europa tem **só 1 e-mail** no SharePoint (`julia.castro@ella.link`) —
  conferir se o cadastro está completo.
