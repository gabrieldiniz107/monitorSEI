"""Configuração via .env."""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    return int(raw) if raw else default


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "sim", "on")


@dataclass(frozen=True)
class Config:
    # Login SEI
    sei_login_url: str = os.getenv("SEI_LOGIN_URL", "").strip()
    sei_email: str = os.getenv("SEI_EMAIL", "").strip()
    sei_password: str = os.getenv("SEI_PASSWORD", "").strip()

    # IMAP (captura do código 2FA)
    imap_host: str = os.getenv("IMAP_HOST", "imap.gmail.com").strip()
    imap_port: int = _int("IMAP_PORT", 993)
    imap_user: str = os.getenv("IMAP_USER", "").strip()
    imap_app_password: str = os.getenv("IMAP_APP_PASSWORD", "").strip()
    sei_code_from: str = os.getenv("SEI_CODE_FROM", "naoresponder_sei@anatel.gov.br").strip()
    sei_code_ttl_min: int = _int("SEI_CODE_TTL_MIN", 10)

    # Navegador
    headless: bool = _bool("HEADLESS", True)
    state_path: str = os.getenv("SEI_STATE_PATH", "state/sei_state.json").strip()

    # Monitoramento de Intimações (Fase 1)
    teams_webhook_url: str = os.getenv("TEAMS_WEBHOOK_INTIMACOES_URL", "").strip()
    teams_webhook_style: str = os.getenv("TEAMS_WEBHOOK_STYLE", "text").strip().lower()
    seen_db_path: str = os.getenv("INTIMACOES_DB_PATH", "state/intimacoes.db").strip()
    # a lista vem ordenada do mais novo p/ o mais antigo → as novas ficam no topo.
    # nº de páginas (100 linhas cada) a raspar por execução do `run`.
    run_paginas: int = _int("INTIMACOES_RUN_PAGINAS", 2)
    # nº de páginas raspadas pelo `baseline` (marca o histórico como visto).
    baseline_paginas: int = _int("INTIMACOES_BASELINE_PAGINAS", 200)
    # teto de segurança: com store vazio, acima disso o run recusa notificar em massa
    seed_max: int = _int("INTIMACOES_SEED_MAX", 50)
    tz_display: str = os.getenv("TZ_DISPLAY", "America/Sao_Paulo").strip()

    # SharePoint / Microsoft Graph (Fase 1b — cross-check de clientes por CNPJ).
    # graph.cliente() lê estas 3 vars de os.environ; ausentes ⇒ segue sem cross-check.
    graph_tenant_id: str = os.getenv("GRAPH_TENANT_ID", "").strip()
    graph_client_id: str = os.getenv("GRAPH_CLIENT_ID", "").strip()
    graph_client_secret: str = os.getenv("GRAPH_CLIENT_SECRET", "").strip()

    # OpenAI (Fase 2 — resumo do ofício/anexos)
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "").strip()
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()

    # Power Automate — criação de rascunho na caixa do Jurídico (Fase 2, Increment 4)
    powerautomate_rascunho_url: str = os.getenv("POWERAUTOMATE_RASCUNHO_URL", "").strip()

    def validate(self) -> None:
        faltando = [
            nome
            for nome, val in (
                ("SEI_LOGIN_URL", self.sei_login_url),
                ("SEI_EMAIL", self.sei_email),
                ("SEI_PASSWORD", self.sei_password),
                ("IMAP_USER", self.imap_user),
                ("IMAP_APP_PASSWORD", self.imap_app_password),
            )
            if not val
        ]
        if faltando:
            raise RuntimeError(f"Config incompleta no .env: {', '.join(faltando)}")


def load_config() -> Config:
    cfg = Config()
    cfg.validate()
    return cfg
