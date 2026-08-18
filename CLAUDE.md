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
atrás de um comando separado (`tratar --modo real`) — nunca no `run` de produção. A **Fase 4**
faz o mesmo para o ofício coletivo (`coletivo --modo real`), com as mesmas travas.

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

| Arquivo              | Responsabilidade                                                                          |
| -------------------- | ----------------------------------------------------------------------------------------- |
| `config.py`        | Carrega o`.env` (dataclass `Config`, `load_config()`).                              |
| `email_code.py`    | Captura o código 2FA via IMAP (`esperar_codigo`).                                      |
| `login.py`         | Login Playwright + 2FA →`LoginSession` (tem `.page`). Chromium com `--no-sandbox`. |
| `intimacoes.py`    | Raspagem +**parser puro** (`parse_pagina`) + navegação (`coletar`).           |
| `models.py`        | `Intimacao`, `Grupo` (dataclasses).                                                   |
| `classificar.py`   | `agrupar_por_oficio` → coletivo vs individual.                                         |
| `store.py`         | Dedup SQLite (`IntimacoesStore`: `ja_visto`/`marcar_visto`/`marcar_lote`).        |
| `clientes.py`      | `SharePointClientes` — cross-check por CNPJ (ver regra de "ativo").                    |
| `graph.py`         | Cliente Microsoft Graph (app-only) do SharePoint "Gestão Integrada".                     |
| `notify.py`        | `formatar_grupo` (texto, p/ dry-run/testes) e `formatar_grupo_html` (Teams) + envio.  |
| `teams.py`         | POST no webhook (estilo`text` = `{"text": "..."}`, ou `card`).                      |
| `monitor.py`       | Orquestrador + CLI:`run` / `baseline` / `dry-run`.                                  |
| `validar_login.py` | Valida só o login (usado p/ testar Turnstile headless).                                  |

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
python -m seibot.monitor prazos     # Fase 3: avisos de prazo (1x/dia, nao acessa o SEI)
python -m seibot.monitor tratar --modo completo --doc-id 16067648   # alveja UMA intimação
python validar_login.py             # valida só o login (teste do Turnstile headless)
python -m seibot.monitor coletivo --modo ensaio                      # Fase 4: lista coletivos candidatos
python -m seibot.monitor coletivo --modo mapear --doc-id 16075320    # READ-ONLY, diagnostica 1 coletivo
python -m seibot.monitor coletivo --modo completo --doc-id 16075320  # tudo, SEM ciencia (ja cumprido)
python -m seibot.monitor coletivo --modo completo --doc-id 16075320,16075999  # varios na MESMA sessao
python -m seibot.monitor coletivo --modo real [--doc-id N[,M]]       # DA CIENCIA e publica a pasta
pytest -q                           # 231 testes (parser/classificar/store/notify/monitor/clientes/coletivo/…)
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
- ~~**Bug em aberto — processo com múltiplas intimações**~~ **CORRIGIDO (2026-08-05)**:
  `tratar --modo completo` ganhou **`--doc-id`**, que casa pelo id do documento em vez do nº do
  processo. Sem ele, um processo com >1 intimação abria a errada (Maxxnet
  `53524.000048/2026-12`, 2 Notificações de Lançamento).

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
`onclick="infraAbrirJanelaModal('…acao=md_pet_intimacao_usu_ext_confirmar_aceite &id_acesso_externo=…&id_documento=…&id_intimacao[]=…&infra_hash=…', 900, 470)"`.
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
anexos → o 1º rascunho foi criado sem a Planilha de Maturidade. `extrair_anexos` (texto)
virou secundário, só ordena. (A fonte primária virou a Lista de Protocolos — e depois foi
corrigida de novo em 2026-07-21, ver "Anexos = documentos da intimação" abaixo.)

**Mudanças de código daí (2026-07-20):** `processo.urls_aceite()` e `processo.dar_ciencia()`;
`tratativa.tratar_um` ganhou `dar_ciencia: bool` e a ordem
correta (**abrir → ciência → reabrir → protocolos → prazo → downloads**), com **checkpoint**
`store.marcar_tratado` logo após a ciência (se o pipeline quebrar depois, o prazo já corre e
o registro não se perde) e **salvaguarda**: se houver ícone de aceite e `dar_ciencia=False`,
aborta sem tocar em nada. `ensaio`/`completo` passam `dar_ciencia=False`; só `real` passa True.
**57 testes.**

### Fase 2 automática — decisão do usuário (2026-07-20)

Rodar **tudo automático** no cron, com **alerta de erro no Teams do responsável técnico**.
Implementado:

- **`seibot/erros.py`** — `notificar_erro(cfg, contexto, exc, critico=)`. **Nunca levanta**
  — falhar ao avisar não pode virar uma segunda falha. Trunca traceback em 2500 chars.
  **Erro NUNCA vai para o grupo do Jurídico** (é ruído; eles não têm o que fazer com isso).

  **Ordem de destino invertida em 18/08/2026** (decisão do Gabriel): primeiro o canal
  **AUTOMAÇÕES - ALERTAS** (`TEAMS_WEBHOOK_ERROS_URL`, webhook do Workflows), e a DM do
  `TEAMS_DEV_EMAIL` como **reserva**. O motivo é a natureza do canal de erro: ele avisa
  quando algo quebrou, e uma das coisas que quebram é o próprio refresh token delegado
  (expira, exige login interativo). Com o webhook na frente, a falha do token continua
  sendo avisada. É o mesmo canal e o mesmo raciocínio dos projetos irmãos
  (`automacaoColetas`, `automacaoVistorias`).

  ⚠️ O card do Teams **não renderiza HTML** — `formatar_erro()` (HTML) serve só à DM; o
  card usa `partes_do_erro()`, que devolve texto puro. Mandar o HTML no card exibiria as
  tags cruas. O layout do card é FactSet (Onde/Erro/Detalhe/Quando) + a última linha do
  traceback em destaque + o traceback completo em monoespaçado. Sem botão de
  "ver detalhes": `Action.ToggleVisibility` nem sempre renderiza em mensagem postada por
  webhook, e esconder o traceback atrás de um botão que não aparece perderia o essencial.
- **`seibot/teams_dm.py`** — DM via **Graph delegado**, porte do
  `automacaoVistorias/cft/src/teams_notify.py`. Chat no Graph **não funciona app-only** →
  login device-code único (`python -m seibot.teams_dm --login`), refresh token em
  `state/.graph_token.json`, cache de `chatId` em `state/.teams_chats.json` (o Graph não
  deduplica chats — sem cache criaria um novo a cada execução). Escopos **delegados**
  `Chat.Create` + `ChatMessage.Send`, mesmo app "SCM VISTORIAS".
  ⚠️ **O refresh token expira**; se morrer, a DM falha e o erro fica só no log (com aviso
  bem visível). Conferir com `python -m seibot.teams_dm --token`.
- **`monitor.main()`** tem `try/except` global: **qualquer** exceção, mapeada ou não, em
  qualquer comando, vira alerta. `run` também alerta falha por ofício.
- **`TRATAR_AUTO`** (novo, default `false`): trava que arma o `--modo real`. Verificada
  **antes do login** (não gasta 2FA). Falha ALTO com mensagem — nunca no-op silencioso.
- **`TratativaIncompleta`** (novo): exceção para falha **depois** da ciência. Estado perigoso —
  prazo correndo + checkpoint bloqueando retry + cliente não avisado ⇒ alerta **🆘 CRÍTICO**
  pedindo ação manual. `tratar_um` separou `_tratar_apos_ciencia()` só para classificar isso.
- **Cron**: `run` em 07/11/14/17h e `tratar --modo real` 10 min depois (não concorrer na sessão).

**66 testes.**

### Regra de adimplência (decisão do usuário, 2026-07-21)

Tratativa automática (que **dá ciência**) exige **ativo E não-inadimplente**. Cliente ativo
porém **inadimplente** não é aberto nem recebe ciência — o Jurídico é avisado na própria
mensagem do `run`, com o motivo, e trata à mão.

- Fonte única da regra: **`clientes.motivo_sem_tratativa(info)`** (`None` = pode tratar).
  Consumida por `tratativa.eh_candidato` (seleção) **e** por `notify._decisao_individual`
  (aviso) — de propósito, para as duas nunca divergirem.
- **Só o inadimplente EXPLÍCITO bloqueia.** `adimplencia is None` (cliente ativo sem registro
  na lista Financeiro) **não** bloqueia. Medido em 2026-07-21: dos **1.082 ativos** → 680
  adimplentes, 210 inadimplentes, **192 sem registro**. Bloquear os 192 jogaria 18% dos
  ativos na fila manual por lacuna de cadastro, não por inadimplência real.
- ⚠️ **O `docker-compose.yml` só monta `./state`** — o código roda **da imagem**. Toda mudança
  de regra exige `docker compose build` antes do próximo cron, senão o container segue com a
  regra velha.

### Anexos = documentos DA INTIMAÇÃO (correção 2026-07-21)

A Lista de Protocolos traz o **processo inteiro**, não a intimação. Usá-la como fonte de
anexos mandou o histórico do processo para o cliente: o rascunho da SPEEDMAX (proc
53500.039627/2026-23) saiu com **14 anexos**.

**Fonte primária agora: os ícones de aceite.** Eles listam exatamente os documentos da
intimação (`doc_principal` + `doc_anexo`) — é a definição do próprio SEI. Medido ao vivo no
proc 53539.000753/2026-51: **aceites = 2** (Ofício 268 + Despacho Decisório 476) enquanto a
**Lista de Protocolos = 4** (sobravam "Consulta CNPJ" e "Consulta", documentos **internos da
Anatel** que não podem ir para o cliente).

- `processo.anexos_da_intimacao(protocolos, doc_id_oficio, docs_intimacao, citados)`
  (substituiu `anexos_de_protocolos`).
- ⚠️ **Os ícones de aceite somem depois da ciência** ⇒ `tratativa.tratar_um` captura os nºs
  **antes** de dar ciência e repassa a `_tratar_apos_ciencia`. Não dá para recuperá-los
  depois — se essa fiação quebrar, cai no fallback silenciosamente.
- **Fallback** (processo já cumprido, sem ícones): só os `(SEI nº …)` citados no texto do
  ofício; se não houver, vai só o ofício. Melhor faltar anexo do que vazar documento interno.
- O rascunho da SPEEDMAX (14 anexos) foi criado ANTES desta correção e **não foi corrigido
  em retrospecto** — conferir à mão antes de enviar.

### Anexos gerados no SEI vêm em HTML, não em PDF (correção 2026-07-22)

Rascunho da **SITELBRA** (proc `53500.064050/2024-26`, Ofício 407 / SEI 15843941): dos 4
arquivos anexados, o **Despacho Decisório 14** (SEI 13227283) e o **Informe 17** (13227113)
**não abriam**; só o ofício e o **Extrato de Lançamentos** (15996728) abriam.

Causa: os anexos eram baixados crus (`processo.baixar` = `context.request.get().body()`) e
salvos com extensão `.pdf`. Mas documentos **gerados dentro do SEI** (Ofício, Despacho,
Informe, Nota Técnica…) **não são PDF** — `documento_consulta_externa.php` os serve como
**HTML** (é por isso que o ofício sempre teve o `oficio_pdf` dedicado, e que
`_tratar_apos_ciencia` decodifica o ofício como ISO-8859-1 para o resumo). HTML salvo como
`.pdf` = arquivo que não abre. Só documentos **externos** (upload — ex.: Extrato) já são PDF.

Fix: **`processo.baixar_como_pdf(page, ctx, url)`** — detecta o magic number `%PDF`; se já é
PDF devolve cru, senão renderiza a página via `page.pdf()` (headless), igual ao ofício.
`tratativa._tratar_apos_ciencia` usa esse helper para os anexos. **94 testes.**

- ⚠️ **Requer `HEADLESS=true`** (page.pdf() só roda headless) — produção já é headless.
- ⚠️ **O rascunho da SITELBRA (e qualquer outro criado antes de 22/07) NÃO foi corrigido em
  retrospecto** — os PDFs quebrados seguem na caixa do Jurídico. Regerar: `monitor tratar --modo completo --processo 53500.064050/2024-26` (já cumprida → sem ciência) cria um novo
  rascunho com os PDFs certos; apagar o antigo à mão.
- **Nuance de contagem de anexos** (não é bug, é decisão pendente): o texto do ofício dizia
  "Anexo: Despacho Decisório" (1 só), mas a intimação eletrônica do SEI empacotou 4 docs
  (ofício + Despacho + Extrato + Informe 17). O bot usa a definição do SEI (ícones de aceite
  = `docs_intimacao`), então mandou os 3. Se o Jurídico quiser restringir ao que o texto
  chama de "Anexo", é outra regra — decidir com eles.

### Prazo "Dias Úteis" não era parseado → "sem prazo de resposta" (correção 2026-07-22)

Rascunho da **Maxxnet** (proc `53524.000048/2026-12`, Notificação de Lançamento 16003317,
**Cobrança de Crédito Tributário**) saiu com **"Prazo: — (sem prazo de resposta)"** no Teams,
no e-mail e no card — mas o prazo EXISTIA e estava legível.

Causa: `#selTipoResposta` trazia `"Impugnação (20 Dias Úteis) - Data Limite: 19/08/2026"`
(prazo em **dias ÚTEIS**, típico de matéria tributária), mas o `_PRAZO_RE` estava preso em
`(N Dias)` — o token `Dias?\s*\)` não casava com `Dias Úteis)` → `parse_prazo` devolvia
`None` → `capturar_prazo` seguia para a próxima opção (só havia a vazia) → prazo `None`.
(Confirmado ao vivo: a intimação já cumprida foi reaberta e o select lido — a opção estava
lá; a tela que o usuário printou parecia "vazia" só porque o `<select>` mostra a 1ª opção
em branco quando fechado.)

Fix em `processo.py`: `_PRAZO_RE` ganhou `(?P<unidade>Dias?(?:\s+[^\s)]+)?)` — casa
`Dias`, `Dias Úteis`, `Dias Corridos`, `Dia Útil`. `Prazo` ganhou o campo **`unidade`**
(default `"dias"`, retrocompatível) e a preserva: dia útil ≠ dia corrido importa
juridicamente. Teams/e-mail agora mostram `20 dias úteis` em vez de `20 dias`. **107 testes**
(regressão em `test_parse_prazo_dias_uteis`).

- O rascunho + card da Maxxnet criados ANTES do fix **não** se autocorrigem — foram remediados
  à mão (rascunhos refeitos por script pontual; card corrigido via PATCH da `DataVencimento`,
  ver os "3 achados" abaixo). **Atenção:** `--modo completo` NÃO servia para regerar aqui —
  este processo tem 2 intimações e o comando pega a errada. O **card** é idempotente por Nº do
  Processo, então re-rodar **não** atualizaria o `DataVencimento` em branco de qualquer forma.
- ✅ **Em produção (2026-07-22):** commit deployado na VPS e `docker compose build` feito — o
  container já roda com o regex novo (e o pypdf, ver "3 achados"). Lembrete permanente: como
  produção roda **da imagem** (`docker-compose.yml` só monta `./state`), toda mudança de código
  exige rebuild antes do próximo cron.

### Mais 3 achados no mesmo processo da Maxxnet ao refazer o rascunho (correção 2026-07-22)

Ao regerar o rascunho da Maxxnet, o proc `53524.000048/2026-12` revelou 3 armadilhas:

**1. Processo com MAIS DE UMA intimação.** Esse processo tem **duas** Notificações de
Lançamento (Cobrança de Crédito Tributário): `16003317` (nº 001-005083, FUST **2023**) e
`16003331` (nº 001-005107, FUST **2024**), cada uma com seu Extrato de Lançamentos anexo
(`15989680` 2023 · `15989702` 2024). O comando **`tratar --modo completo/real` casa por
`x.processo == processo_alvo` e pega o PRIMEIRO grupo** → em processo multi-intimação abre a
intimação errada. ⚠️ **Bug em aberto**: `--processo` não desambigua; para alvejar uma
intimação específica seria preciso casar por `doc_id`. Por ora, num processo multi-intimação,
o `--modo completo` não é confiável — foi feito um script pontual por `doc_id`.

**2. Ofício SERVIDO COMO PDF vira resumo-lixo (CORRIGIDO).** A Notificação de Lançamento é
entregue por `documento_consulta_externa.php` como **PDF de verdade** (`%PDF`, print externo),
não HTML. O `_tratar_apos_ciencia` decodificava tudo como ISO-8859-1 → o LLM resumia **bytes
binários** (resumo genérico/inventado). Fix: **`processo.extrair_texto_oficio(bytes)`** —
`%PDF` → extrai via **pypdf** (nova dep); senão decodifica HTML como antes. E o **anexo do
próprio ofício** agora usa os bytes crus quando já é PDF (antes `oficio_pdf()` re-renderizava
um PDF já-PDF pela impressora do Chromium). `eh_pdf()` centraliza a detecção. **110 testes**
(`test_extrair_texto_oficio_*`). Validado ao vivo: resumo passou a citar o valor real
(R$ 6.414,70) e os fatos do Fust. ✅ Já em produção — a nova dep **pypdf** entrou no
`requirements.txt` e o `docker compose build` foi feito na VPS (2026-07-22).

**3. Anexo não é recuperável depois da ciência.** Em processo já **cumprido** os ícones de
aceite sumiram e estes ofícios **não citam `(SEI nº …)`** no texto → `anexos_da_intimacao`
devolve **0**. Ao refazer um rascunho de intimação já cumprida, o anexo tem de ser **apontado
à mão** (o par Notificação↔Extrato do mesmo exercício). Reforça o que já estava dito: só dá
para pegar o anexo automaticamente ANTES da ciência (via ícones de aceite).

Rascunhos corretos recriados (script pontual, por `doc_id`, sem ciência): 16003317 (Extrato
2023) e 16003331 (Extrato 2024), ambos prazo 19/08/2026, ofício+extrato, resumo do PDF real.
Os rascunhos velhos/errados no `juridico@` foram deixados para apagar à mão. O **card** do
processo (id 35, ofício 16003317) foi corrigido via PATCH cirúrgico: `DataVencimento`=19/08/2026
(a coluna calculada `PrazoOficio` recalculou p/ 28 dias); os demais campos, inclusive o
`TipoOficio`/`StatusOficio` que o Jurídico já editara, foram preservados.

### Tratativa abandonada em silêncio + prazo jogado fora (incidente 2026-08-05)

Em 05/08 às 07:00 o `run` notificou uma intimação **individual, Pendente, URGENTE**, cliente
**ativo e adimplente** (proc `53500.098046/2026-23`, Ofício 688 `16067648`, Age
Telecomunicações), com a linha "▶️ seguir com a tratativa individual". O `tratar --modo real`
das 07:10 **não a tratou e ninguém soube**.

Nos logs da VPS, tudo estava saudável: cron instalado, `TRATAR_AUTO=true`, execução das 07:10
logou, coletou 100 e terminou `{"status":"ok"}` imprimindo **`0 candidato(s)`**; o canal de DM
está vivo (`teams_dm --token` OK). Ou seja: `tratativa.eh_candidato` a **descartou em silêncio**
— era o único caminho do sistema sem rastro. Causa provável: **alguém do Jurídico abre a
intimação no SEI antes do cron**, a Situação vira "Cumprida por Consulta Direta" e o bot deixa
de enxergá-la. O mesmo log mostra o padrão em 03/08 (Ofício 630, `16000695`): falhou com
`ofício não achado na Lista de Protocolos`, **sem** a linha `⚠️ DANDO CIÊNCIA` (ou seja
`urls_aceite()` já vinha vazio), nunca entrou em `tratadas` — e ainda assim sumiu da seleção
nas execuções seguintes.

**⚠️ Bug de produção achado junto: o prazo era capturado e descartado.** As 12 linhas de
`tratadas` na VPS estavam com `data_limite` **vazio**, inclusive a FONELIGHT cujo log da mesma
execução mostrava `prazo: 03/09/2026`. `store.marcar_tratado` usava `INSERT OR IGNORE` e o
`--modo real` grava **duas vezes**: o checkpoint pós-ciência (sem prazo — ele só é legível
depois) e a gravação final com o prazo. A segunda era descartada. Só se manifesta no
`--modo real` (o `--modo completo` não dá ciência, logo não faz checkpoint) — por isso nunca
apareceu em dev.

**O que mudou:**

- `store.marcar_tratado` virou **UPSERT** (`ON CONFLICT … DO UPDATE … WHERE excluded.data_limite != ''`):
  a condição impede que um checkpoint tardio apague um prazo já gravado. Ganhou `prazo_dias` e
  `prazo_unidade` (dia útil ≠ dia corrido). Migração in-place por `ALTER TABLE` no `__init__`
  (`_garantir_colunas`) — o banco de produção é volume, não dá para recriar.
- **Nova tabela `promessas`** + `registrar_promessa` / `promessas_abertas` / `quitar_promessa` /
  `marcar_promessa_avisada`. O `run` registra o que prometeu (mesma condição de
  `notify._decisao_individual`, **após** o envio bem-sucedido); o `tratar --modo real`
  reconcilia no fim (`monitor._reconciliar_promessas`).
- `tratativa.eh_candidato` → **`motivo_nao_candidato(g, clientes, promessa_aberta=)`**, que
  devolve o motivo em texto (espelha `clientes.motivo_sem_tratativa`). Toda promessa não
  cumprida rende aviso **no grupo do Jurídico** (`notify.formatar_promessa_nao_cumprida`) com o
  motivo; erro técnico continua indo só para a DM.
- **Ciência dada por humano deixa de cancelar a tratativa**: `motivo_nao_candidato` aceita
  `Cumprida por Consulta Direta`/`por Decurso do Prazo Tácito` **somente com promessa aberta**.
  ⚠️ Esse escopo é a **salvaguarda principal** — aceitar amplamente faria o próximo
  `--modo real` tratar todo o histórico cumprido da janela de 100 linhas, disparando dezenas
  de rascunhos a clientes de uma vez. "Respondida" nunca volta (não há o que encaminhar).
- `backfill_prazos.py` (raiz) recupera as 12 linhas antigas a partir do `DataVencimento` dos
  **cards do Kanban** (que nunca teve o bug), casando por processo + `doc_id` do `NumeroOficio`.
  `--aplicar` para gravar; sem a flag é ensaio.

**139 testes.** ⚠️ Produção roda **da imagem** → `docker compose build` na VPS antes do próximo
cron, senão o container segue sem nada disso.

⚠️ **`pytest` mandava Teams de verdade.** `config.py` avalia `os.getenv(...)` nos *defaults de
campo* da dataclass (no import, logo após `load_dotenv`), então `Config()` dentro de teste **é a
config de produção**: `test_erro_ao_enviar_nao_marca_e_reenvia` fazia `erros.notificar_erro`
disparar DM real (os alertas "ofício 10/20 · P10/P20" de 05/08 vieram daí, não de produção) e
ainda rotacionava o refresh token em `state/.graph_token.json`. Mitigado no `_cfg()` do
`test_monitor.py` (zera todos os canais de saída). A correção de fundo — `conftest.py` na raiz
neutralizando `load_dotenv` e limpando o `os.environ` **antes** de importar `seibot` — segue
pendente por decisão do usuário.

### Fase 4 — ofício COLETIVO: ciência + pasta compartilhada (2026-08-07)

Ofício que a Anatel manda para **várias empresas de uma vez**. Comando **`monitor coletivo
--modo {ensaio|mapear|completo|real}`**. O bot abre → dá ciência (**uma** cobre todos os
destinatários) → baixa ofício + anexos → **publica na biblioteca compartilhada com os
clientes** → avisa o Teams com o link. **Sem e-mail** — publicar na pasta É a entrega.
(**Card e acompanhamento de prazo entraram em 2026-08-10** — ver a seção logo abaixo.)
Detalhe completo em `FASE-4-COLETIVO.md`.

- `seibot/coletivo.py` (pipeline), `seibot/biblioteca.py` (publicação), escrita em drive no
  `graph.py` (`item_do_drive` / `garantir_pasta` / `upload_arquivo`).
- Destino: site **CLIENTESEPARCEIROS** → biblioteca **DOCUMENTOS** → `Ofícios Jurídicos
  Anatel/Ofício N (docid)`. Mesmo app app-only "SCM VISTORIAS" — nenhuma credencial nova.
- Seleção: **todo coletivo com ≥1 destinatário Pendente**, sem olhar cliente ativo (o ofício
  é indivisível e a pasta é do ofício, não da empresa).
- `--modo real` tem as travas do individual (`TRATAR_AUTO=true` + dia útil, antes do login) e
  aceita **`--doc-id`** para alvejar ofícios específicos — **vários separados por vírgula**,
  tratados na MESMA sessão (um login = um código 2FA na caixa de uma pessoa real).
- ⚠️ **Anexo do coletivo = o que o TEXTO do ofício cita** (`extrair_anexos`), e **não** os
  documentos que o SEI empacotou na intimação — o oposto da Fase 2. No 693 o SEI empacotou 3
  anexos, mas a Planilha "Tabela ISPs/Domínios" (16075319) não é do ofício e não pode ir ao
  cliente; o texto citava os 2 corretos. Contrapartida aceita: ofício que não cita um anexo
  real deixa o cliente sem ele (caso do Ofício 70) — por isso **o individual não mudou**.
- ⚠️ **Coletivo TEM prazo, e curto**: os 9 da janela de 07/08 eram todos URGENTE com 5 dias.
  Vai destacado com ⚠️ no Teams e, desde 10/08, **entra no acompanhamento da Fase 3**.
- Validado ao vivo em 07/08/2026: ciência real no **Ofício 693** (9 empresas, 1 confirmação,
  prazo 14/08) e pastas publicadas de 693 e 697.

### Coletivo entrou no acompanhamento de prazos, com card (2026-08-10)

A decisão de 07/08 (coletivo fora da Fase 3, prazo "controlado à mão") caiu junto com a
premissa de que coletivo raramente tem prazo. Agora ele é acompanhado **como o individual**.

- **Card no Kanban** via `oficio_card.montar_campos_coletivo` / `criar_card_coletivo`,
  nascendo em **`STATUS_AGUARDANDO`** — a raia-gatilho da Fase 3. As 4 raias reais de
  `StatusOficio` (conferidas ao vivo em 10/08): Aguardando documentação (cliente) · Minuta de
  defesa em elaboração · Defesa enviada · Processo concluído.
- **1 card por ofício, SEM CNPJ/Email/Telefone/Pacote** — são N empresas e o lookup só
  apontaria para uma. Elas e o link da pasta ficam no comentário de proveniência
  (`comentarios.texto_card_coletivo`).
- **Card só quando há prazo.** Sem prazo não há o que acompanhar.
- **1 lembrete por ofício.** Um coletivo rende N linhas em `tratadas` (uma por empresa);
  `monitor._unidades_de_aviso` colapsa por `(processo, doc_id)`. ⚠️ Aviso, parada e "sem card"
  gravam em **todas** as chaves da unidade — marcar só a representativa faria as outras N-1
  voltarem no dia seguinte.
- `tratadas` ganhou **`grupo_tipo`** ('individual'|'coletivo') e **`pasta_url`** (o link entra
  no lembrete, que é o item acionável). Migração in-place em `_garantir_colunas`.
- Saíram do código: `coletivo.MOTIVO_SEM_CARD` e o `parar_acompanhamento` que desligava o
  acompanhamento do coletivo no ato de registrá-lo.
- ⚠️ **Sem card não há acompanhamento**: a criação é best-effort (não derruba a publicação já
  feita), então o alerta na DM do responsável técnico diz explicitamente que o prazo ficará
  sem acompanhamento se o card falhar.
- ⚠️ `marcar_tratado` só grava de fato quando `data_limite != ''` (proteção do prazo, ver o
  incidente de 05/08) — numa tratativa **sem** prazo, `oficio_desc`/`grupo_tipo`/`pasta_url`
  não chegam ao banco. Não afeta o acompanhamento (que exige prazo), mas confunde ao debugar.

### ⚠️ A coluna "Ações" é lazy — e isso derrubava a ciência em silêncio (2026-08-07)

Causa-raiz do "bloqueio" da Fase 4 e, muito provavelmente, das falhas silenciosas do
individual em 03/08 (Ofício 630) e 05/08 (Age Telecomunicações).

A coluna "Ações" da Lista de Protocolos **não vem no HTML**: cada linha traz um
`<div class="md-pet-acao-lazy">` e um loader que busca os botões por AJAX
(`get_acoes_protocolo_lista`), **um documento por vez, encadeado**. Num processo com ~105
documentos (o do Ofício 693) a cadeia leva dezenas de segundos, e o `abrir_processo` espera
~11s → `urls_aceite()` devolvia `[]`. E `[]` significa **"ciência já dada"** ⇒ o bot seguia
sem por onde entrar, ou descartava a intimação sem rastro. Rolar mais não resolve: o custo é
de rede, não de viewport.

**Fix:** `processo._aceites_lazy` chama o endpoint direto, decodifica o HTML dos botões e
junta ao que o DOM já mostrava. No 693: de 0 para 4 ícones de aceite.

⚠️ **O endpoint responde HTTP 500 quando o lote é grande** (medido em 07/08/2026 no ofício
682, com 16 itens). Por isso `buscar()` no JS **nunca levanta**: tenta o lote e, se ele
falhar, refaz **item a item** — que é como o loader nativo do SEI sempre faz. A primeira
versão fazia `r.json()` solto, então o 500 virava exceção, o fallback nunca rodava e
`urls_aceite()` voltava vazio (= "ciência já dada"). Foi o que derrubou 682 e 666 no lote.

Três consertos vieram junto:

- **`processo.CienciaIncerta`** — na primeira ciência real o `click()` estourou em
  `waiting for scheduled navigations to finish` **depois** de `click action done`: a ciência
  entrou, mas o erro subiu como falha comum, o checkpoint não foi gravado e nada foi
  publicado (e no ciclo seguinte o ofício sairia da seleção em silêncio, por não ter mais
  destinatário Pendente). Agora o clique usa `no_wait_after=True` e, se ainda assim falhar,
  vira `CienciaIncerta` — que `tratativa`/`coletivo` tratam como **ciência dada**: gravam o
  checkpoint e alertam como falha pós-ciência.
- **`processo.escolher_aceite(aceites, doc_id)`** — o marcador `doc_principal` nem sempre vem
  (no 693 os 4 ícones vieram com `principal=False`), então passa a casar pelo nº do ofício
  primeiro. Usado pelo individual e pelo coletivo.
- **`processo.baixar`** ganhou timeout de 120s + 3 tentativas: o
  `documento_consulta_externa.php` passou dos 30s padrão no Ofício 693, e falhar ali é
  *depois* da ciência.
- **`coletivo._aceites_de_pendente`** — "sem ícone de aceite" só é estado válido quando
  **não há destinatário Pendente**. Havendo, relê a página até 3x (e retenta erro de
  navegação, que derrubou o ofício 663) e, se ainda assim nada, **aborta sem tocar em nada**.
  Antes o bot seguia como "ciência já dada", quebrava adiante em "ofício não achado na Lista
  de Protocolos" e a intimação ficava Pendente sem ninguém ter dado ciência.

### Fase 3 — acompanhamento de prazos (feature 2026-08-05)

Comando novo **`monitor prazos`**, 1x/dia às 08:30 no cron. **Não acessa o SEI**: lê a tabela
`tratadas` e a lista do Kanban. Fonte da verdade do "ainda está pendente" é a **raia do
card**, não o SEI.

**Gatilho:** enquanto o card estiver em **"Aguardando documentação (cliente)"**, o prazo é
contado e o lembrete vai para o **grupo do Jurídico** (mesmo webhook do `run`). Ao sair da
raia, a contagem para e sai **uma** mensagem de encerramento. ⚠️ Parar de contar **não**
significa processo resolvido — a mensagem diz isso explicitamente, a pedido do usuário.

**A raia é consultada ANTES de qualquer aviso** (exigência do usuário): se o card já saiu,
o que sai é a mensagem de parada, nunca mais um lembrete.

**Cobre individual e coletivo** (desde 2026-08-10). O coletivo entra com **um** lembrete por
ofício: suas N linhas em `tratadas` (uma por empresa) colapsam em `monitor._unidades_de_aviso`
por `(processo, doc_id)`, e todo desfecho é gravado em todas as chaves da unidade.

**Cadência** (`seibot/prazos.py`, tudo puro):

| Prazo | Avisa a cada |
|---|---|
| 5 dias | 1 dia | 
| 10 dias | 2 dias |
| 15 dias | 3 dias |
| 20 dias | 4 dias |
| 30 dias | 5 dias |

Prazo fora da tabela **arredonda para o degrau inferior** (6→5, 12→10, 25→20, 45→30);
abaixo de 5, avisa todo dia. `prazo_dias` nulo (as 10 linhas recuperadas pelo backfill, que
só trouxe a data) também cai em diário — na dúvida, insiste.

⚠️ **A cadência é ancorada no VENCIMENTO**, não na ciência: avisa quando
`dias_restantes % intervalo == 0`. Assim **o dia do vencimento sempre é coberto**. Consequência
a não estranhar: num prazo de 22 dias (intervalo 4) o primeiro aviso sai quando faltam 20, não
22. Cadência em **dias corridos** — a data limite já vem pronta da Anatel, então não se depende
de tabela de feriados.

⚠️ **Aviso que cairia em sábado/domingo é ANTECIPADO para a sexta anterior** (decisão do
usuário, 2026-08-05). **Antecipar preserva o prazo restante; empurrar para segunda o
consumiria** — e era justamente o alerta mais crítico que caía em fim de semana (simulado: num
prazo de 20 dias iniciado numa sexta, a "última chance" caía num domingo). A mensagem sinaliza
`📅 Aviso antecipado`. Prazo **vencido** também só é avisado em dia útil — como ele insiste
diariamente, a segunda cobre o fim de semana.

Estados do aviso: normal (`⏳ faltam N`), **última chance**, vencimento (`🔴 VENCE HOJE`) e
**vencido** (`🆘`, diário até moverem o card).

**"Última chance"** = não há mais nenhum aviso agendado **estritamente antes** do dia do
vencimento (`prazos._ha_aviso_antes_do_vencimento`). Definir assim — e não como
`faltam == intervalo` — foi necessário em dois casos: quando o próprio vencimento cai em fim
de semana (a sexta vira o último aviso possível) e quando o último checkpoint pré-vencimento é
antecipado. O dia do vencimento **não** conta como "mais um aviso", porque ali já é tarde para
montar defesa ou pedir dilação. É o gancho da automação futura de **defesa/dilação de prazo**.

**Sem card no Kanban** → avisa o grupo e encerra o acompanhamento: sem raia não dá para
saber se ainda está pendente. (Acontece com tratativas anteriores a 22/07, quando a feature
de card não existia, e com processo multi-intimação — ver o bug do card abaixo.)

**Mudanças de apoio:**
- `oficio_card`: o card agora **nasce em "Aguardando documentação (cliente)"** (`STATUS_AGUARDANDO`)
  em vez de ficar sem raia. Card sem raia = prazo não acompanhado.
- `store.tratadas` ganhou `oficio_desc`, `empresa`, `acomp_estado`, `acomp_motivo`,
  `acomp_ultimo_aviso` (dedup do dia, para o comando poder ser rodado à mão sem duplicar).
- `seibot/datas.py`: `eh_dia_util` / `proximo_dia_util` / conversões do formato do SEI.
- `monitor.acompanhar_prazos(store=, cards=, hoje=, enviar=)` — núcleo com injeção de
  dependência, igual ao `executar`; `_cmd_prazos` é só a casca que monta store/cards/webhook.

### A automação inteira só roda em dia útil (2026-08-10)

Generalização da trava abaixo, a pedido do usuário: **fim de semana é off para tudo que o
cron dispara**, não só para os comandos que dão ciência.

- `monitor._pular_fim_de_semana` barra **`run`** e **`prazos`** em sábado/domingo, **antes**
  de qualquer trabalho (no `run` isso evita gastar um código 2FA num dia em que ninguém vai
  agir). `tratar`/`coletivo --modo real` já tinham a sua trava.
- Comandos de operação — `dry-run`, `baseline`, `--modo ensaio/mapear/completo` — **seguem
  rodando qualquer dia**: são ferramentas de quem está ao teclado.
- O cron da VPS também virou `* * 1-5` nas 4 linhas. Cinto e suspensório de propósito.
- ⚠️ Feriado continua não sendo considerado (ver a nota do `datas.py`).

### Ciência só em dia útil (2026-08-05)

`tratar --modo real` **sai sozinho em sábado e domingo**, antes do login (não gasta 2FA),
igual à trava do `TRATAR_AUTO`. Iniciar prazo legal fora de dia útil é decisão do Jurídico,
não da automação. As candidatas continuam `Pendente` e são pegas na segunda; a promessa
segue aberta e a reconciliação **não** dispara falso alarme (ela só avisa quando o grupo
deixou de ser candidato).

⚠️ **Feriados não são considerados** — só sábado/domingo (`datas.eh_dia_util`), decisão
consciente do usuário (2026-08-05). Uma tabela de feriados nacionais/municipais precisaria ser
mantida à mão e erraria em silêncio ao desatualizar. Enquanto isso, o bot **pode dar ciência
num feriado** e **pode avisar prazo em feriado**.

### Card do ofício no Kanban do Jurídico (feature 2026-07-22)

Ao final de cada tratativa (quando cria o rascunho), o bot também cria um **card** na lista
**"Jurídico - Controle de Ofício"** (`ControleOficioJuridico`, id
`407dc958-8ac3-4224-9026-d0759149a235`, site Gestão Integrada). É a lista do Kanban que o
time do Jurídico usa; as raias do board = o campo `StatusOficio`.

- **`seibot/oficio_card.py`**: `montar_campos` (puro) + `criar_card` (idempotente por Nº do
  Processo — não duplica se já existe; seguro re-rodar `--modo completo`).
- **O que o bot preenche**: `Title` (nº processo), `NumeroOficio` (`Ofício N (docid)`),
  `CNPJ` (lookup → Clientes SCM, via `CNPJLookupId`) + `CNPJsemFormatacao`, `DataCumprimento`
  (dia da ciência), `DataVencimento` (prazo), `Email`, `Telefone`, **`Prioridade`**
  (URGENTE→`Alta`, senão `Média`) e **`Pacote`** (tier do contrato ativo).
- **O que fica EM BRANCO de propósito** (Jurídico edita conforme conduz): `StatusOficio`,
  `TipoOficio` (não mapeava 1:1 com os tipos do SEI), `LoginSEI`/`SenhaSEI`, insumos do AGU.
  ⚠️ **`DataAGUfim` é coluna CALCULADA (read-only)** — o bot NÃO a toca; ela exibe
  `30/12/1899` em todo item sem AGU (inclusive os manuais). Só muda na fórmula da coluna.
- **CNPJ é lookup** para a lista **Clientes SCM** (confirmado ao vivo: item 3539 = CNPJ do
  card). O id vem de `clientes.ClienteInfo.sp_item_id` (novo); telefones vêm de `field_4`/
  `TelefoneFinanceiro`/`TelefoneTecnico`/`TelefoneAdm` (`ClienteInfo.telefones`, novo).
- **`Pacote`**: vem do campo **`Servicos`** (multi-choice) da lista **Comercial** — o tier do
  contrato **ativo** (`clientes.ClienteInfo.pacote`, via `_melhor_pacote`). Com >1 tier (~5%
  dos clientes), prefere conectividade (`BLACK>ULTRA>FLEX>LIGHT`); `JURÍDICO` só se não houver
  outro. ⚠️ **Ranking é palpite** — ajustar `_TIERS_RANK` se o Jurídico definir diferente.
  ⚠️ `Pacote` é **multi-choice** no SEI → grava-se **lista** + `"Pacote@odata.type":
  "Collection(Edm.String)"` (sem a anotação o Graph dá 500/400).
- **Comentário de proveniência** (pedido do usuário, padrão CREA/CFT): `seibot/comentarios.py`
  posta *"[Automação Jurídico] 🤖 Card criado automaticamente…"* no card. Comentário de item
  **não existe no Graph** — é **SharePoint REST** (`_api/web/lists(...)/items(id)/Comments`) e
  **delegado** (autor = usuário; app-only dá 401). **Reaproveita o refresh token do
  `teams_dm`** (`state/.graph_token.json`) redimido p/ o escopo SharePoint `AllSites.Write`
  (validado 2026-07-22) — **um login device-code cobre DM de erro + comentário**. Best-effort
  (cosmético; se falhar, só loga).
- **`SharePointClientes.graph`** (novo) expõe o cliente Graph app-only p/ escrita; **Graph
  escreve** via `graph.criar_item` (POST, novo). Comentário usa auth delegada à parte.
- **Best-effort**: `tratativa._criar_card_best_effort` — falha ao criar o card **não** derruba
  a tratativa (ciência + rascunho já concluídos); só loga e manda DM de erro (não-crítico).
- **Validado ao vivo (2026-07-22)** no card da SITELBRA (item 34): `Pacote=['LIGHT']`,
  `Prioridade='Média'`, lookup resolveu a Razão Social, datas/contatos OK, Status/Tipo em
  branco, e comentário de automação postado e lido de volta. **104 testes.**

### ⚠️ Riscos conhecidos ao ligar (leia antes de armar `TRATAR_AUTO=true`)

- **`processo.dar_ciencia()` nunca executou.** No pendente real a ciência foi dada pelo script
  de mapeamento (`ciencia.py`, descartável), não por essa função. Ela reproduz exatamente o
  que funcionou (mesma URL de modal, mesmo `#sbmAceitarIntimacao`, com guarda se o botão
  sumir), mas o **primeiro uso em produção é o primeiro uso real do código**. O `--modo completo` **não** cobre isso: ele passa `dar_ciencia=False` por construção.
- **`--modo real` como comando também nunca rodou** ponta a ponta (o laço de seleção +
  ciência). Só suas partes.
- **Falha pós-ciência não tem retry** — por design (evita ciência dupla). Depende de humano
  reagir ao alerta crítico.
- **O login device-code da DM ainda não foi feito** — sem `state/.graph_token.json` nenhum
  erro é notificado (só log). Rodar `python -m seibot.teams_dm --login` e testar com
  `--teste "ping"` **antes** de armar `TRATAR_AUTO=true`.
- **Sem fallback para o grupo** (decisão do usuário, 2026-07-20): se a DM falhar, o erro fica
  só no log. Trade-off aceito para não poluir o grupo do Jurídico.
- Faltam **ajustes de texto/tom do e-mail** ao cliente (template em `rascunho.py`).
- Cliente Cabos Brasil Europa tem **só 1 e-mail** no SharePoint (`julia.castro@ella.link`) —
  conferir se o cadastro está completo.
