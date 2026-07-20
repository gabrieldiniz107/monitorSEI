# monitoramento-sei

Bot **autocontido** de monitoramento do **SEI Acesso Externo (Anatel)** para o Jurídico
da SCM — Item 1 do plano (ver `../CLAUDE.md`).

Loga na conta única do Rodrigo (procurador de todos os provedores), **captura o próprio
código 2FA** por e-mail (IMAP, somente leitura) e lê a tela de **Intimações Eletrônicas**
para detectar processos/ofícios/intimações e prazos.

> ⚠️ **Regra de ouro (Fase 1):** o monitoramento só **lê** as listagens, nunca dá ciência.
> A **Fase 2** dá ciência de propósito, mas só para intimação individual de cliente ATIVO e
> atrás de comando separado (`tratar --modo real` + `TRATAR_AUTO=true`).
>
> Detalhe que corrige um mal-entendido antigo: **abrir o processo NÃO dá ciência**. A ciência
> é um passo explícito — o modal `confirmar_aceite` + botão `#sbmAceitarIntimacao`. Só esse
> clique inicia o prazo.

## Estrutura
```
monitoramento-sei/
├── seibot/
│   ├── config.py       # carrega .env
│   ├── email_code.py   # busca o código 2FA do SEI via IMAP (readonly)
│   ├── login.py        # login Playwright + 2FA autocapturado
│   ├── intimacoes.py   # raspagem da tela Intimações + parser puro
│   ├── models.py       # Intimacao, Grupo
│   ├── classificar.py  # agrupa por ofício → coletivo vs individual
│   ├── store.py        # dedup SQLite (o que já foi notificado)
│   ├── notify.py       # formata + envia p/ Teams
│   ├── teams.py        # webhook (Power Automate/Workflows)
│   ├── clientes.py     # (Fase 1b) base de clientes SharePoint por CNPJ
│   ├── sessao.py       # (Fase 2) reaproveita cookies p/ não relogar a cada passo
│   ├── processo.py     # (Fase 2) abrir processo, DAR CIÊNCIA, prazo, ofício/anexos
│   ├── resumo.py       # (Fase 2) resumo do ofício via OpenAI
│   ├── rascunho.py     # (Fase 2) monta e cria o rascunho de e-mail no Jurídico
│   ├── tratativa.py    # (Fase 2) seleção de candidatos + orquestração da tratativa
│   ├── erros.py        # alerta de QUALQUER falha na DM do responsável técnico
│   ├── teams_dm.py     # DM no Teams via Graph delegado (device-code)
│   └── monitor.py      # orquestrador + CLI (run/baseline/dry-run/tratar)
├── validar_login.py    # milestone 1: valida só o login
├── capturar_html.py    # util: salva o HTML da tela p/ calibrar o parser
├── tests/              # pytest (parser, classificar, store, notify, monitor)
├── Dockerfile · docker-compose.yml · DEPLOY.md
├── requirements.txt
└── .env                # segredos (gitignored)
```

## Comandos (Fase 1)
```bash
python -m seibot.monitor dry-run    # mostra o que seria notificado (sem banco/Teams)
python -m seibot.monitor baseline   # marca os recentes como vistos (1x, sem notificar)
python -m seibot.monitor run        # detecta novos e notifica no Teams
```
Agendado 4x/dia (07/11/14/17h) via cron na VPS — ver `DEPLOY.md`.

**Como detecta novidade:** a tela vem ordenada do mais novo p/ o mais antigo; o `run`
raspa a 1ª página (100 mais recentes), agrupa por ofício (mesmo ofício p/ várias empresas
= *coletivo*; uma só = *individual*), deduplica contra o SQLite e notifica só o que é novo.
Nunca abre processo nem clica em "Ações" (isso daria ciência e iniciaria o prazo).

**Cross-check de clientes (Fase 1b):** se as credenciais `GRAPH_*` estiverem no `.env`,
cada empresa é cruzada por CNPJ com o SharePoint "Gestão Integrada" (`seibot/clientes.py`
+ `graph.py`, via Microsoft Graph app-only). Anota na notificação: **ativo** (regra de
união: `StatusContrato=Ativo` na lista *Clientes SCM* OU contrato *Ativo* na lista
*Comercial*), **não-ativo** (com o status), ou **fora da base**; e a **adimplência**
(lista *Financeiro*). Sem `GRAPH_*`, o bot segue só com a Fase 1a.

## Comandos (Fase 2 — tratativa individual)
```bash
python -m seibot.monitor tratar --modo ensaio                  # só lista candidatos
python -m seibot.monitor tratar --modo completo --processo NNN # ensaio-geral (sem ciência)
python -m seibot.monitor tratar --modo real                    # produção — DÁ CIÊNCIA
```
Para cada intimação **nova + individual + cliente ATIVO + Pendente**: abre o processo,
**dá ciência**, lê o prazo, baixa ofício e anexos, resume com LLM, e cria um **rascunho** de
e-mail ao cliente na caixa do Jurídico (humano revisa e envia). Reporta tudo no Teams.

`--modo real` exige `TRATAR_AUTO=true` no `.env` — trava deliberada, verificada antes do
login. **Anexos vêm da Lista de Protocolos**, não do texto do ofício (o ofício nem sempre
cita todos).

## Erros
Qualquer exceção, mapeada ou não, vira **DM no Teams** do `TEAMS_DEV_EMAIL` (Graph delegado,
mesmo padrão do `automacaoVistorias`). Nunca vai para o grupo do Jurídico. Login único:
```bash
python -m seibot.teams_dm --login    # device-code, uma vez
python -m seibot.teams_dm --teste "ping"
python -m seibot.teams_dm --token    # confere escopos (o refresh token expira!)
```
Falha **depois** da ciência é marcada como **🆘 crítica**: o prazo já corre, não há retry
automático (checkpoint no store) e o cliente não foi avisado — exige ação manual.

## Por que Playwright (e não requests)
A tela de login carrega **Cloudflare Turnstile**, que passa invisível num navegador real
mas bloquearia um cliente HTTP puro. Além disso o SEI usa `infra_hash` (token anti-CSRF
por sessão) que invalida a sessão se reusado — então navega-se seguindo links frescos.

## Rodar local
```bash
cd monitoramento-sei
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/playwright install chromium
.venv/bin/python validar_login.py     # abre o navegador, loga, pega o código e confirma
```

## Config (.env)
- `SEI_EMAIL` / `SEI_PASSWORD` — conta do Rodrigo no Acesso Externo.
- `IMAP_USER` / `IMAP_APP_PASSWORD` — Gmail do Rodrigo (senha de app), p/ ler o código 2FA.
- `HEADLESS` — `false` mostra o navegador (validação); `true` p/ servidor.
