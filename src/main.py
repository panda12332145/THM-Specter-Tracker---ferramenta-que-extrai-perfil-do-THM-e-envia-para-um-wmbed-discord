"""Orquestração principal do THM Specter Tracker."""

from __future__ import annotations

import sys
from typing import Any, Dict, List, Optional

from src.bootstrap import configure_console_utf8, ensure_dependencies
from src.config import parse_config


def print_report(data: Dict[str, Any]) -> None:
    """Exibe resumo formatado dos dados extraídos no terminal."""
    profile = data.get("profile") or {}
    rooms = data.get("completed_rooms") or []
    badges = data.get("badges") or []
    source_labels = {
        "api_http": "API Pública v2 (HTTP direto)",
        "api_browser": "API Pública v2 (Contexto Chromium)",
        "dom_browser": "DOM Next.js (Playwright)",
    }
    source_desc = source_labels.get(str(data.get("source")), str(data.get("source", "N/A")))

    print("\n" + "=" * 58)
    print(f"  👻 THM SPECTER TRACKER — {profile.get('username', 'N/A')}")
    print("=" * 58)
    print(f"  📡 Fonte de coleta : {source_desc}")
    print(f"  🔗 Perfil          : {profile.get('profile_url', 'N/A')}")
    print(f"  🎚️  Level           : {profile.get('level', 'N/A')}")
    print(f"  🏆 Rank            : {profile.get('rank', 'N/A')}")
    if profile.get("total_points") is not None:
        print(f"  ⭐ Pontos          : {profile['total_points']:,}")
    if profile.get("league") and profile.get("league") != "N/A":
        print(f"  💎 Liga            : {profile['league']}")
    print(f"  🔥 Streak          : {profile.get('streak', 'N/A')}")
    print(f"  🚪 Salas (total)   : {profile.get('completed_rooms', 'N/A')} (listadas: {len(rooms)})")
    print(f"  🏅 Badges (total)  : {profile.get('badges', 'N/A')} (listados: {len(badges)})")
    if profile.get("capability_score") is not None:
        pov = f" ({profile['capability_pov']})" if profile.get("capability_pov") else ""
        print(f"  ⚡ Capability      : {profile['capability_score']}{pov}")
    if rooms:
        sample_rooms = ", ".join(rooms[:5])
        more_r = f" ... (+{len(rooms) - 5})" if len(rooms) > 5 else ""
        print(f"  🏁 Primeiras salas : {sample_rooms}{more_r}")
    if badges:
        sample_badges = ", ".join(b.get("name", "") for b in badges[:5] if isinstance(b, dict))
        more_b = f" ... (+{len(badges) - 5})" if len(badges) > 5 else ""
        print(f"  🎖️  Primeiros badges: {sample_badges}{more_b}")
    print("=" * 58)


def main(argv: Optional[List[str]] = None) -> int:
    """Função principal de execução da CLI."""
    configure_console_utf8()

    try:
        cfg = parse_config(argv=argv)
    except ValueError as exc:
        print(f"[ERRO] {exc}", file=sys.stderr)
        return 1

    try:
        ensure_dependencies(
            auto_install=cfg.auto_install,
            install_browsers=cfg.install_browsers,
        )
    except RuntimeError as exc:
        print(f"[ERRO] {exc}", file=sys.stderr)
        return 1

    from src.collector import CollectorError, ProfileNotFoundError, collect_all
    from src.discord_webhook import send_webhook
    from src.storage import save_json

    print(f"[INFO] Coletando perfil público do TryHackMe: '{cfg.username}'...")
    try:
        data = collect_all(
            username=cfg.username,
            max_rooms=cfg.max_rooms,
            force_browser=cfg.force_browser,
            headless=cfg.headless,
            timeout_ms=cfg.timeout_ms,
        )
    except ProfileNotFoundError as exc:
        print(f"[ERRO] {exc}", file=sys.stderr)
        return 1
    except CollectorError as exc:
        print(f"[ERRO] Falha durante a coleta no TryHackMe: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"[ERRO] Erro inesperado na coleta: {exc}", file=sys.stderr)
        return 1

    print_report(data)

    try:
        saved_path = save_json(data, cfg.output_file)
        print(f"[OK] Dados salvos com sucesso em: {saved_path}")
    except OSError as exc:
        print(f"[ERRO] Falha ao salvar arquivo JSON '{cfg.output_file}': {exc}", file=sys.stderr)
        return 1

    if cfg.no_webhook:
        print("[INFO] Envio ao Discord desativado (--no-webhook).")
    elif cfg.webhook_url:
        send_webhook(data, cfg.webhook_url)
    else:
        print(
            "[INFO] Nenhum Webhook configurado (use --webhook ou defina DISCORD_WEBHOOK_URL no .env para enviar ao Discord)."
        )

    print("[OK] Execução concluída com sucesso!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
