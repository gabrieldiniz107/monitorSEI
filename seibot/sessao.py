"""Abertura de sessão REAPROVEITANDO os cookies salvos (state/sei_state.json).

Evita pedir código 2FA a cada ação: enquanto a sessão do SEI estiver viva, reusa os
cookies; só faz login novo (2FA) se a sessão expirou. Ideal para tarefas com vários
passos em sequência (exploração, tratativa) sem relogar toda hora.

Uso:
    from seibot.sessao import abrir
    with abrir(cfg, permitir_login=False) as sess:   # não faz login novo; erro se expirou
        page = sess.page
        ...
"""
from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright

from .config import Config
from .login import LoginSession, fazer_login


class SessaoExpirada(RuntimeError):
    pass


def _esta_logado(page, cfg: Config) -> bool:
    """Vai à URL de login; se a sessão estiver viva, o SEI redireciona para a área
    logada (sem o formulário de e-mail)."""
    try:
        page.goto(cfg.sei_login_url, wait_until="commit")
    except Exception:
        pass
    page.wait_for_timeout(2000)
    return page.locator("#txtEmail").count() == 0


def abrir(cfg: Config, *, permitir_login: bool = True, log=print) -> LoginSession:
    """Reaproveita a sessão salva se ainda válida; senão faz login novo (se permitido)."""
    state = Path(cfg.state_path)
    if state.exists():
        pw = sync_playwright().start()
        browser = pw.chromium.launch(
            headless=cfg.headless, args=["--no-sandbox", "--disable-dev-shm-usage"])
        context = browser.new_context(storage_state=str(state))
        page = context.new_page()
        try:
            if _esta_logado(page, cfg):
                log("→ Sessão reaproveitada (cookies válidos, sem novo login/2FA).")
                # renova o state (prorroga a validade dos cookies)
                try:
                    context.storage_state(path=cfg.state_path)
                except Exception:
                    pass
                return LoginSession(pw, browser, context, page, cfg)
            log("→ Sessão salva expirou.")
        except Exception as e:
            log(f"  (aviso ao reusar sessão: {e})")
        for fn in (context.close, browser.close, pw.stop):
            try:
                fn()
            except Exception:
                pass

    if not permitir_login:
        raise SessaoExpirada("Sessão expirada e login novo não autorizado agora.")
    return fazer_login(cfg, log=log)
