"""Login no SEI Acesso Externo (Anatel) com Playwright — autocontido.

Por que Playwright e não `requests`: a página de login carrega Cloudflare Turnstile,
que passa de forma invisível num navegador real mas bloquearia um cliente HTTP puro.
O Playwright executa o JS da página como um navegador de verdade.

Fluxo:
1. Abre a tela de login e preenche e-mail + senha.
2. Marca o instante do disparo (para só aceitar um código 2FA recebido depois disso).
3. Clica em ENTRAR → o SEI envia um código de 6 dígitos ao e-mail do Rodrigo.
4. Busca o código sozinho via IMAP (seibot.email_code).
5. Preenche o código e valida → cai em "Controle de Acessos Externos".
6. Salva os cookies/sessão em disco (state) para reaproveitar.

⚠️ Este módulo NÃO clica em cadeados/ações que deem ciência. Só autentica.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from playwright.sync_api import Page, TimeoutError as PWTimeout, sync_playwright

from .config import Config
from .email_code import esperar_codigo

# URL de destino após login bem-sucedido (tela inicial do acesso externo)
SUCESSO_MARCADOR = "usuario_externo_controle_acessos"


class LoginError(RuntimeError):
    pass


def _preencher_login(page: Page, cfg: Config) -> None:
    page.goto(cfg.sei_login_url, wait_until="domcontentloaded")
    page.fill("#txtEmail", cfg.sei_email)
    page.fill("#pwdSenha", cfg.sei_password)


def _esta_logado(page: Page) -> bool:
    return SUCESSO_MARCADOR in page.url


def fazer_login(cfg: Config, log=print) -> "LoginSession":
    """Executa o login completo (com 2FA autocapturado) e devolve a sessão ativa."""
    Path(cfg.state_path).parent.mkdir(parents=True, exist_ok=True)

    pw = sync_playwright().start()
    # --no-sandbox: obrigatório ao rodar Chromium como root no container Docker.
    # --disable-dev-shm-usage: evita crash por /dev/shm pequeno em containers.
    browser = pw.chromium.launch(
        headless=cfg.headless,
        args=["--no-sandbox", "--disable-dev-shm-usage"],
    )
    context = browser.new_context()
    page = context.new_page()

    try:
        log("→ Abrindo tela de login do SEI…")
        _preencher_login(page, cfg)

        # tolerância de relógio: aceita código a partir de 90s antes do clique
        apos = datetime.now(timezone.utc) - timedelta(seconds=90)

        log("→ Enviando e-mail+senha (dispara o código 2FA)…")
        page.click("#sbmLogin")

        # aparece o campo de código (placeholder "Código de Acesso")
        try:
            page.wait_for_selector("input[placeholder='Código de Acesso']", timeout=20000)
        except PWTimeout:
            if _esta_logado(page):
                log("→ Já autenticado sem 2FA (sessão lembrada).")
                return LoginSession(pw, browser, context, page, cfg)
            raise LoginError(
                "Não apareceu o campo de código 2FA nem caiu logado. "
                "Verifique credenciais ou se o Turnstile bloqueou."
            )

        log("→ Buscando o código 2FA no e-mail (IMAP)…")
        codigo = esperar_codigo(cfg, apos=apos, timeout_s=120, intervalo_s=5)
        log(f"→ Código recebido: {codigo}")

        page.fill("input[placeholder='Código de Acesso']", codigo)
        page.click("button:has-text('Validar')")

        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(1500)

        if not _esta_logado(page):
            # às vezes precisa de um instante extra para redirecionar
            try:
                page.wait_for_url(f"**{SUCESSO_MARCADOR}**", timeout=10000)
            except PWTimeout:
                pass

        if not _esta_logado(page):
            raise LoginError(
                f"Validação do código não levou à tela esperada. URL atual: {page.url}"
            )

        context.storage_state(path=cfg.state_path)
        log(f"✓ Logado. Sessão salva em {cfg.state_path}")
        return LoginSession(pw, browser, context, page, cfg)

    except Exception:
        context.close()
        browser.close()
        pw.stop()
        raise


class LoginSession:
    """Sessão autenticada viva. Use como context manager para fechar tudo no fim."""

    def __init__(self, pw, browser, context, page, cfg):
        self._pw = pw
        self.browser = browser
        self.context = context
        self.page = page
        self.cfg = cfg

    def __enter__(self) -> "LoginSession":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        for fn in (self.context.close, self.browser.close, self._pw.stop):
            try:
                fn()
            except Exception:
                pass
