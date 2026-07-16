# Imagem oficial do Playwright já traz Chromium + dependências do sistema.
# A tag casa com playwright==1.48.0 do requirements.txt (não baixar browser de novo).
FROM mcr.microsoft.com/playwright/python:v1.48.0-jammy

ENV PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY seibot/ ./seibot/
COPY validar_login.py capturar_html.py ./

# execução efêmera (o cron do host chama `docker compose run --rm ...`)
CMD ["python", "-m", "seibot.monitor", "run"]
