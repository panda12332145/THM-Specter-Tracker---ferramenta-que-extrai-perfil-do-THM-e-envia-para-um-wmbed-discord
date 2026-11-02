"""Verificação e instalação automática de dependências (pip + Playwright Chromium)."""

from __future__ import annotations

import importlib
import importlib.util
import os
import site
import subprocess
import sys
from typing import Iterable, Tuple

REQUIRED_LIBRARIES: Tuple[Tuple[str, str], ...] = (
    ("requests", "requests>=2.31.0"),
    ("playwright", "playwright>=1.40.0"),
)


def configure_console_utf8() -> None:
    """Garante codificação UTF-8 no console (evita UnicodeEncodeError no CMD do Windows)."""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def _in_virtualenv() -> bool:
    base_prefix = getattr(sys, "base_prefix", sys.prefix)
    real_prefix = getattr(sys, "real_prefix", None)
    return bool(real_prefix or sys.prefix != base_prefix or os.environ.get("VIRTUAL_ENV"))


def _refresh_import_paths() -> None:
    """Atualiza caches e user site-packages para importar pacotes recém-instalados na mesma execução."""
    try:
        user_site = site.getusersitepackages()
        if isinstance(user_site, str) and os.path.isdir(user_site):
            if user_site not in sys.path:
                sys.path.append(user_site)
            site.addsitedir(user_site)
    except Exception:
        pass
    importlib.invalidate_caches()


def _pip_install(package_spec: str) -> bool:
    """Tenta instalar um pacote via pip lidando com venv, Windows e PEP 668 (Linux)."""
    base_cmd = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check"]

    if _in_virtualenv():
        candidates = [[*base_cmd, package_spec]]
    elif os.name == "nt":
        candidates = [
            [*base_cmd, package_spec],
            [*base_cmd, "--user", package_spec],
        ]
    else:
        candidates = [
            [*base_cmd, "--user", package_spec],
            [*base_cmd, "--user", "--break-system-packages", package_spec],
            [*base_cmd, "--break-system-packages", package_spec],
        ]

    last_err = ""
    for cmd in candidates:
        try:
            proc = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=300,
            )
            if proc.returncode == 0:
                _refresh_import_paths()
                return True
            last_err = (proc.stderr or proc.stdout or "").strip()
        except Exception as exc:
            last_err = str(exc)

    print(f"[ERRO] Falha ao instalar '{package_spec}' automaticamente: {last_err}", file=sys.stderr)
    return False


def ensure_playwright_chromium() -> bool:
    """Instala ou atualiza o binário Chromium do Playwright quando necessário."""
    print("[SETUP] Baixando/verificando navegador Chromium do Playwright...")
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            timeout=600,
        )
        return proc.returncode == 0
    except Exception as exc:
        print(f"[AVISO] Não foi possível instalar o Chromium automaticamente: {exc}", file=sys.stderr)
        return False


def ensure_dependencies(
    packages: Iterable[Tuple[str, str]] = REQUIRED_LIBRARIES,
    auto_install: bool = True,
    install_browsers: bool = False,
) -> None:
    """Garante que todas as bibliotecas exigidas estejam instaladas antes da execução."""
    configure_console_utf8()

    if os.environ.get("THM_NO_AUTO_INSTALL", "").strip() == "1":
        auto_install = False

    missing = [
        (mod_name, pip_spec)
        for mod_name, pip_spec in packages
        if importlib.util.find_spec(mod_name) is None
    ]

    for mod_name, pip_spec in missing:
        if not auto_install:
            raise RuntimeError(
                f"Dependência '{mod_name}' ausente. Instale com: pip install -r requirements.txt"
            )
        print(f"[SETUP] Biblioteca '{mod_name}' não encontrada. Instalando automaticamente ({pip_spec})...")
        if not _pip_install(pip_spec) or importlib.util.find_spec(mod_name) is None:
            raise RuntimeError(
                f"Não foi possível instalar '{pip_spec}'. Execute manualmente: {sys.executable} -m pip install -r requirements.txt"
            )
        print(f"[OK] Biblioteca '{mod_name}' instalada com sucesso!")

    if install_browsers:
        ensure_playwright_chromium()
