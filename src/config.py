"""Configuração do THM Specter Tracker (CLI, variáveis de ambiente e arquivo .env)."""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse

DEFAULT_USERNAME = "CyberOwl"
DEFAULT_OUTPUT_FILE = "tryhackme_profile.json"
DEFAULT_MAX_ROOMS = 500
DEFAULT_TIMEOUT_MS = 60000


@dataclass
class TrackerConfig:
    """Parâmetros consolidados de execução."""

    username: str = DEFAULT_USERNAME
    webhook_url: str = ""
    output_file: str = DEFAULT_OUTPUT_FILE
    max_rooms: int = DEFAULT_MAX_ROOMS
    force_browser: bool = False
    headless: bool = True
    no_webhook: bool = False
    auto_install: bool = True
    install_browsers: bool = False
    timeout_ms: int = DEFAULT_TIMEOUT_MS


def normalize_username(raw: str) -> str:
    """Extrai o slug do usuário mesmo que uma URL completa (tryhackme.com/p/...) seja informada."""
    val = (raw or "").strip()
    if not val:
        return ""

    if "://" in val or val.lower().startswith("tryhackme.com"):
        if "://" not in val:
            val = "https://" + val
        parsed = urlparse(val)
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) >= 2 and parts[0].lower() == "p":
            val = parts[1]
        elif parts:
            val = parts[-1]

    val = val.split("?")[0].split("#")[0].strip().strip("/")
    # Permite apenas caracteres válidos em slugs de perfil (evita injeção em querystring/path)
    if not re.match(r"^[A-Za-z0-9_.\-]{1,64}$", val):
        raise ValueError(
            f"Username inválido: '{raw}'. Informe apenas o nome do perfil (ex.: CyberOwl)."
        )
    return val


def load_dotenv_file(dotenv_path: Optional[Path] = None) -> Dict[str, str]:
    """Carrega pares CHAVE=VALOR de um arquivo .env sem depender de bibliotecas externas."""
    if dotenv_path is None:
        dotenv_path = Path(__file__).resolve().parent.parent / ".env"

    loaded: Dict[str, str] = {}
    if not dotenv_path.is_file():
        return loaded

    try:
        content = dotenv_path.read_text(encoding="utf-8")
    except OSError:
        return loaded

    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if key:
            loaded[key] = value
            os.environ.setdefault(key, value)

    return loaded


def save_dotenv_file(
    dotenv_path: Path,
    username: str,
    webhook_url: str,
    output_file: str = DEFAULT_OUTPUT_FILE,
    max_rooms: int = DEFAULT_MAX_ROOMS,
) -> None:
    """Salva configurações básicas em .env de forma atômica."""
    tmp_path = dotenv_path.with_suffix(".env.tmp")
    body = (
        f"THM_USERNAME={username}\n"
        f"DISCORD_WEBHOOK_URL={webhook_url}\n"
        f"THM_OUTPUT_FILE={output_file}\n"
        f"THM_MAX_ROOMS={max_rooms}\n"
    )
    tmp_path.write_text(body, encoding="utf-8")
    os.replace(tmp_path, dotenv_path)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="thm-specter-tracker",
        description="Extrai estatísticas, salas e badges públicos do TryHackMe e envia para um Webhook do Discord.",
    )
    parser.add_argument(
        "-u",
        "--username",
        help="Username público do TryHackMe (ou URL https://tryhackme.com/p/<user>)",
    )
    parser.add_argument(
        "-w",
        "--webhook",
        help="URL do Webhook do Discord (ou defina DISCORD_WEBHOOK_URL no .env)",
    )
    parser.add_argument(
        "-o",
        "--output",
        help=f"Caminho do arquivo JSON de saída (padrão: {DEFAULT_OUTPUT_FILE})",
    )
    parser.add_argument(
        "--max-rooms",
        type=int,
        default=None,
        help=f"Limite máximo de salas concluídas a paginar (0 = todas, padrão: {DEFAULT_MAX_ROOMS})",
    )
    parser.add_argument(
        "--browser",
        action="store_true",
        help="Força coleta via navegador Playwright (útil se o IP sofrer bloqueio anti-bot HTTP)",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Abre o Chromium com janela visível quando o modo navegador for utilizado",
    )
    parser.add_argument(
        "--no-webhook",
        action="store_true",
        help="Não envia para o Discord (apenas exibe no terminal e salva o JSON)",
    )
    parser.add_argument(
        "--no-auto-install",
        action="store_true",
        help="Desativa a instalação automática de bibliotecas ausentes via pip",
    )
    parser.add_argument(
        "--install-browsers",
        action="store_true",
        help="Instala/atualiza explicitamente o binário Chromium do Playwright",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT_MS,
        help=f"Timeout de navegação em milissegundos (padrão: {DEFAULT_TIMEOUT_MS})",
    )
    return parser


def parse_config(
    argv: Optional[List[str]] = None,
    interactive: Optional[bool] = None,
    dotenv_path: Optional[Path] = None,
) -> TrackerConfig:
    """Resolve parâmetros combinando CLI > variáveis de ambiente > .env > prompt interativo."""
    if dotenv_path is None:
        dotenv_path = Path(__file__).resolve().parent.parent / ".env"

    dotenv_values = load_dotenv_file(dotenv_path)
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if interactive is None:
        interactive = bool(sys.stdin and sys.stdin.isatty())

    env_username = os.environ.get("THM_USERNAME", "").strip()
    env_webhook = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    env_output = os.environ.get("THM_OUTPUT_FILE", "").strip()
    env_max_rooms = os.environ.get("THM_MAX_ROOMS", "").strip()

    raw_username = (args.username or env_username or "").strip()
    prompted_user = False

    if not raw_username and interactive:
        try:
            typed = input(f"👤 Username do TryHackMe [{DEFAULT_USERNAME}]: ").strip()
            raw_username = typed or DEFAULT_USERNAME
            prompted_user = True
        except (EOFError, KeyboardInterrupt):
            print()
            raw_username = DEFAULT_USERNAME

    if not raw_username:
        raw_username = DEFAULT_USERNAME

    username = normalize_username(raw_username)

    no_webhook = bool(args.no_webhook)
    webhook_url = ""
    if not no_webhook:
        webhook_url = (args.webhook or env_webhook or "").strip()
        webhook_configured_in_env = "DISCORD_WEBHOOK_URL" in dotenv_values or bool(env_webhook)
        if not webhook_url and interactive and args.webhook is None and not webhook_configured_in_env:
            try:
                webhook_url = input(
                    "🔗 Discord Webhook URL (Enter para pular envio ao Discord): "
                ).strip()
            except (EOFError, KeyboardInterrupt):
                print()
                webhook_url = ""

            if (prompted_user or webhook_url) and not dotenv_path.exists():
                try:
                    save_ans = input("💾 Deseja salvar essas configurações em .env? [s/N]: ").strip().lower()
                    if save_ans in ("s", "sim", "y", "yes"):
                        save_dotenv_file(dotenv_path, username=username, webhook_url=webhook_url)
                        print(f"[OK] Configurações salvas em {dotenv_path}")
                except (EOFError, KeyboardInterrupt, OSError):
                    pass

    output_file = (args.output or env_output or DEFAULT_OUTPUT_FILE).strip()

    if args.max_rooms is not None:
        max_rooms = max(0, args.max_rooms)
    elif env_max_rooms.isdigit():
        max_rooms = int(env_max_rooms)
    else:
        max_rooms = DEFAULT_MAX_ROOMS

    return TrackerConfig(
        username=username,
        webhook_url=webhook_url,
        output_file=output_file,
        max_rooms=max_rooms,
        force_browser=bool(args.browser),
        headless=not bool(args.headed),
        no_webhook=no_webhook,
        auto_install=not bool(args.no_auto_install),
        install_browsers=bool(args.install_browsers),
        timeout_ms=max(5000, int(args.timeout)),
    )
