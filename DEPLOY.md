# Deploy — monitoramento-sei (VPS Docker)

Roda na mesma VPS do `scm-watchers`. Execução **efêmera** (login pesado + navegador),
disparada pelo **cron do host** 4x/dia. Só conexões de saída; nenhuma porta exposta.

## 1. Subir o código e configurar
```bash
git clone <repo> && cd SCM-Juridico/monitoramento-sei
cp .env.example .env   # (ou copiar o .env) e preencher:
#   SEI_EMAIL / SEI_PASSWORD
#   IMAP_USER / IMAP_APP_PASSWORD   (Gmail do Rodrigo, senha de app)
#   TEAMS_WEBHOOK_INTIMACOES_URL    (webhook do fluxo do Power Automate)
#   HEADLESS=true
mkdir -p state
docker compose build
```

## 2. ⚠️ Validar o Turnstile em headless (GATING)
A tela de login tem Cloudflare Turnstile. Passa invisível num navegador real, mas
**pode bloquear headless no servidor**. Teste isolado ANTES de agendar:
```bash
docker compose run --rm sei-monitor python validar_login.py
```
Se falhar (não passa do login), rodar sob display virtual (xvfb) com HEADLESS=false:
```bash
docker compose run --rm sei-monitor xvfb-run -a python validar_login.py
```
Se o xvfb resolver, use o mesmo prefixo `xvfb-run -a` nos comandos de cron abaixo.

## 3. Baseline (uma vez)
Marca as intimações mais recentes como já vistas (para o 1º `run` não notificar o
histórico). Não envia nada ao Teams:
```bash
docker compose run --rm sei-monitor python -m seibot.monitor baseline
```

## 4. Agendar no cron do host (07/11/14/17h, America/Sao_Paulo)
`crontab -e`:
```cron
CRON_TZ=America/Sao_Paulo
# Fase 1 — monitorar e notificar (somente leitura)
0 7,11,14,17 * * * cd /opt/monitorSEI && docker compose run --rm sei-monitor python -m seibot.monitor run >> /var/log/sei-monitor.log 2>&1
# Fase 2 — tratativa individual (DÁ CIÊNCIA). 10 min após o run, para não concorrer na sessão.
10 7,11,14,17 * * * cd /opt/monitorSEI && docker compose run --rm sei-monitor python -m seibot.monitor tratar --modo real >> /var/log/sei-tratativa.log 2>&1
```
(Se precisou de xvfb: `... run --rm sei-monitor xvfb-run -a python -m seibot.monitor run ...`)

## 5. Canal de erros — DM no Teams (login único)

Erros vão para a **DM do responsável técnico**, não para o grupo do Jurídico. Usa Microsoft
Graph com auth **delegada** (chat no Graph não funciona app-only), mesmo padrão do
`automacaoVistorias` (CFT/CREA), mesmo app registration "SCM VISTORIAS".

Pré-requisitos no app registration (já existem para as vistorias):
- Permissões **DELEGADAS** `Chat.Create` + `ChatMessage.Send` + admin consent.
- Authentication → "Allow public client flows" = **Yes**.

No `.env`: `TEAMS_DEV_EMAIL=gabriel.albuquerque@scmengenharia.com.br`

Login **uma vez** (device-code — abre um código para digitar no navegador):
```bash
docker compose run --rm sei-monitor python -m seibot.teams_dm --login
docker compose run --rm sei-monitor python -m seibot.teams_dm --teste "ping do monitorSEI"
```
O refresh token fica em `state/.graph_token.json` (volume, sobrevive ao container) e o
`chatId` em `state/.teams_chats.json` — o Graph **não** deduplica chats, sem esse cache cada
execução criaria um chat novo.

⚠️ **O refresh token expira.** Se morrer, a DM falha e o erro fica só em
`/var/log/sei-tratativa.log` (com aviso bem visível). Confira de tempos em tempos:
```bash
docker compose run --rm sei-monitor python -m seibot.teams_dm --token
```

## 6. ⚠️ Armar a Fase 2 (ciência automática)

O `tratar --modo real` **dá ciência sozinho**, o que **inicia prazo legal e é irreversível**.
Por isso ele só roda com `TRATAR_AUTO=true` no `.env`.

Sem isso o comando recusa rodar (falha alto, com mensagem — não é no-op silencioso).
**Deixe `false` até a DM de erro estar funcionando** (passo 5 testado), senão uma falha no
meio da tratativa fica sem ninguém sabendo — e o caso pior é justamente esse (ver abaixo).

### Falha depois da ciência = ação manual
Se o pipeline quebrar **após** a ciência (ex.: OpenAI fora do ar, Power Automate recusando),
o estado é: prazo correndo, cliente **não** avisado, e o checkpoint no `store` **impede o
retry automático** (para não dar ciência duas vezes). Isso vira um alerta
**🆘 ERRO CRÍTICO** no Teams, com processo/empresa/ofício — quem receber precisa concluir a
tratativa à mão. Não ignorar esse alerta.

### Quem recebe o quê
| Destino | Conteúdo |
|---|---|
| Grupo "monitor sei juridico" | intimações novas (Fase 1) + resumo de cada tratativa (Fase 2) |
| DM do `TEAMS_DEV_EMAIL` | **qualquer** exceção, mapeada ou não, com traceback |

Erro de automação **nunca** vai para o grupo — é ruído para o time jurídico e não há o que
eles façam a respeito.

## Comandos úteis
- `python -m seibot.monitor dry-run` — mostra o que seria notificado, sem tocar banco/Teams.
- `python -m seibot.monitor run` — detecta e notifica.
- `python -m seibot.monitor baseline` — marca recentes como vistos, sem notificar.
- `python -m seibot.monitor tratar --modo ensaio` — lista candidatos à tratativa, sem abrir nada.
- `python -m seibot.monitor tratar --modo completo --processo <nº>` — ensaio-geral num processo
  **já cumprido**: roda tudo e cria rascunho de verdade, **sem** dar ciência.
- `python -m seibot.monitor tratar --modo real` — produção da Fase 2 (**DÁ CIÊNCIA**).

O `state/` (volume) guarda `intimacoes.db` (dedup + tabela `tratadas`) e `sei_state.json`.
Não versionar.
