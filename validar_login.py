"""Valida a etapa de login do bot SEI (com 2FA autocapturado via e-mail).

Uso:
    cd monitoramento-sei
    .venv/bin/python validar_login.py

Sucesso = o bot loga sozinho, busca o próprio código no e-mail e chega em
"Controle de Acessos Externos". NÃO clica em nada que dê ciência.
"""
from __future__ import annotations

from seibot.config import load_config
from seibot.login import fazer_login


def main() -> int:
    cfg = load_config()
    print(f"Config OK. headless={cfg.headless} | e-mail={cfg.sei_email}")
    with fazer_login(cfg) as sess:
        titulo = sess.page.title()
        url = sess.page.url
        print("\n================ RESULTADO ================")
        print(f"Título da página : {titulo}")
        print(f"URL              : {url}")
        # conta quantos processos a conta enxerga (texto "Lista de Acessos Externos (N ...")
        try:
            corpo = sess.page.inner_text("body")
            import re
            m = re.search(r"Lista de Acessos Externos \((\d+) registros", corpo)
            if m:
                print(f"Processos na conta: {m.group(1)}")
        except Exception:
            pass
        print("✓ LOGIN VALIDADO — o bot autenticou sozinho.")
        print("==========================================")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
