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
0 7,11,14,17 * * * cd /caminho/SCM-Juridico/monitoramento-sei && docker compose run --rm sei-monitor python -m seibot.monitor run >> /var/log/sei-monitor.log 2>&1
```
(Se precisou de xvfb: `... run --rm sei-monitor xvfb-run -a python -m seibot.monitor run ...`)

## Comandos úteis
- `python -m seibot.monitor dry-run` — mostra o que seria notificado, sem tocar banco/Teams.
- `python -m seibot.monitor run` — detecta e notifica.
- `python -m seibot.monitor baseline` — marca recentes como vistos, sem notificar.

O `state/` (volume) guarda `intimacoes.db` (dedup) e `sei_state.json`. Não versionar.
