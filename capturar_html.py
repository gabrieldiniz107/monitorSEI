"""Captura o HTML real da tela 'Intimações Eletrônicas' para calibrar o parser.

Loga (2FA autocapturado), segue o link fresco do menu (por causa do infra_hash),
detecta se há iframe e salva o HTML em tests/fixtures/. NÃO clica em Ações/lupa.

Uso:
    cd monitoramento-sei && .venv/bin/python capturar_html.py
"""
from __future__ import annotations

from pathlib import Path

from seibot.config import load_config
from seibot.login import fazer_login

LINK_INTIMACOES = "a[href*='md_pet_intimacao_usu_ext_listar']"
FIXTURES = Path("tests/fixtures")


def main() -> int:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    cfg = load_config()
    with fazer_login(cfg) as sess:
        page = sess.page
        print("→ Login ok. Seguindo link fresco de Intimações Eletrônicas…")
        href = page.locator(LINK_INTIMACOES).first.get_attribute("href")
        print(f"→ href fresco: {href}")
        page.set_default_navigation_timeout(60000)
        try:
            page.goto(href, wait_until="commit")
        except Exception as e:
            print(f"  (aviso goto: {e})")
        # espera a tabela aparecer, sem depender de 'load' (SEI mantém conexões abertas)
        try:
            page.wait_for_selector("table", timeout=30000)
        except Exception as e:
            print(f"  (aviso wait table: {e})")
        page.wait_for_timeout(2500)

        # detecta iframe de conteúdo (comum no SEI)
        frames = [f for f in page.frames if f != page.main_frame]
        print(f"→ URL: {page.url}")
        print(f"→ Frames além do principal: {len(frames)}")

        (FIXTURES / "intimacoes_page.html").write_text(page.content(), encoding="utf-8")
        print(f"✓ Salvo tests/fixtures/intimacoes_page.html ({len((page.content()))} chars)")

        for idx, fr in enumerate(frames):
            try:
                html = fr.content()
                nome = FIXTURES / f"intimacoes_frame_{idx}.html"
                nome.write_text(html, encoding="utf-8")
                print(f"✓ Frame {idx}: {fr.url}  → {nome} ({len(html)} chars)")
            except Exception as e:
                print(f"  frame {idx}: erro ao ler ({e})")

        page.screenshot(path=str(FIXTURES / "intimacoes.png"))
        print("✓ Screenshot salvo em tests/fixtures/intimacoes.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
