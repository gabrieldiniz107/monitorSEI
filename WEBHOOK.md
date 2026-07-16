# Ligar o webhook do Teams (Power Automate)

O bot manda a notificação como um POST JSON `{"text": "..."}` para uma URL de webhook.
Quem recebe e posta no grupo do Teams é um fluxo do **Power Automate**. Passo a passo:

## 1. Criar o fluxo

1. Acesse **make.powerautomate.com** logado com a conta que deve **aparecer como remetente**
   (ex.: a conta do Rodrigo, se quiser que a mensagem saia "de você").
2. **Criar → Fluxo de nuvem instantâneo** → gatilho **"Quando uma solicitação HTTP é recebida"**
   (*When a HTTP request is received*).
3. No gatilho, em **Esquema JSON do corpo da solicitação**, cole:
   ```json
   { "type": "object", "properties": { "text": { "type": "string" } } }
   ```

## 2. Ação: postar no Teams

4. **+ Nova etapa → Microsoft Teams → "Postar mensagem em um chat ou canal"**
   (*Post message in a chat or channel*).
5. Configure:
   - **Postar como**: *Usuário* (para sair da sua conta) ou *Flow bot*.
   - **Postar em**: *Chat de grupo* → selecione (ou crie) o grupo com **Cauã, Dra. Reisla e Rodrigo**.
     (ou *Canal*, se preferir um canal em vez de chat de grupo).
   - **Mensagem**: clique no campo, abra **Expressão** e insira:
     ```
     triggerBody()?['text']
     ```
6. **Salvar**. O gatilho HTTP vai gerar uma **URL** (aparece no card do gatilho após salvar).
   Copie essa URL — é o webhook.

## 3. Plugar no bot

7. No arquivo `monitoramento-sei/.env`, preencha:
   ```
   TEAMS_WEBHOOK_INTIMACOES_URL=<cole a URL aqui>
   ```

## 4. Testar

8. Teste o webhook **isolado** (deve aparecer uma mensagem no grupo):
   ```bash
   curl -X POST -H "Content-Type: application/json" \
     -d '{"text":"teste do monitor SEI ✅"}' "<URL do webhook>"
   ```
9. Teste o **dry-run** (não envia nada, só mostra o que enviaria):
   ```bash
   cd monitoramento-sei && .venv/bin/python -m seibot.monitor dry-run
   ```
10. **Baseline** (marca o que já existe como visto, sem notificar — roda 1x):
    ```bash
    .venv/bin/python -m seibot.monitor baseline
    ```
11. **Run real** (detecta e notifica de verdade):
    ```bash
    .venv/bin/python -m seibot.monitor run
    ```

    A partir daqui, só intimações **novas** (não vistas antes) geram mensagem.

## Observações

- A URL do webhook é **secreta** (quem tiver ela posta no grupo). Fica só no `.env` (gitignored).
- Se o gatilho "HTTP request" pedir plano **premium** e não estiver disponível, alternativa:
  usar um **Incoming Webhook** num canal do Teams (posta como conector, não como você) — nesse
  caso é só colar a URL do conector no mesmo `TEAMS_WEBHOOK_INTIMACOES_URL`.
- Estilo do payload: o bot manda `{"text": "..."}` (compatível com o passo 5). Se um dia trocar
  para Adaptive Card, mudar `TEAMS_WEBHOOK_STYLE=card` no `.env`.
