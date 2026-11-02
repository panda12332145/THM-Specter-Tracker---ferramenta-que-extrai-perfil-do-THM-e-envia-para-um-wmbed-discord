"""Construção validada de embeds e envio resiliente via Webhook do Discord."""

from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List
from urllib.parse import urlparse

WEBHOOK_REGEX = re.compile(
    r"^https://(?:(?:ptb|canary)\.)?discord(?:app)?\.com/api/webhooks/\d+/[\w.\-]+/?$",
    re.IGNORECASE,
)

DIFFICULTY_EMOJI = {
    "info": "🔵",
    "easy": "🟢",
    "medium": "🟡",
    "hard": "🔴",
    "insane": "🟣",
}

RARITY_EMOJI = {
    "common": "⚪",
    "rare": "🔵",
    "epic": "🟣",
    "legendary": "🟡",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_http_url(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    parsed = urlparse(value.strip())
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def is_valid_discord_webhook(url: str) -> bool:
    """Valida se a string corresponde a uma URL oficial de Webhook do Discord."""
    if not isinstance(url, str):
        return False
    cleaned = url.strip().split("?")[0]
    return bool(WEBHOOK_REGEX.match(cleaned))


def _safe_field(value: Any, fallback: str = "N/A") -> str:
    """Garante string não-vazia de até 1024 caracteres para campos de embed do Discord."""
    if value is None:
        return fallback
    text = str(value).strip()
    if not text:
        return fallback
    return text[:1021] + "..." if len(text) > 1024 else text


def _truncate_lines(lines: List[str], max_chars: int = 1800) -> str:
    """Junta linhas respeitando rigorosamente o limite de caracteres do embed."""
    if not lines:
        return "Nenhum registro público encontrado."
    kept: List[str] = []
    total = 0
    for line in lines:
        addition = len(line) + (1 if kept else 0)
        if total + addition > max_chars - 30:
            kept.append("...")
            break
        kept.append(line)
        total += addition
    return "\n".join(kept)


def build_discord_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    """Constrói o payload JSON de embeds respeitando todos os limites da API do Discord."""
    if not isinstance(data, dict):
        raise ValueError("Dados de entrada inválidos para geração do embed.")

    profile = data.get("profile")
    if not isinstance(profile, dict) or not str(profile.get("username") or "").strip():
        raise ValueError("Perfil vazio ou sem 'username' — coleta não foi concluída.")

    username = str(profile["username"]).strip()
    timestamp = str(data.get("timestamp") or _utc_now())

    fields: List[Dict[str, Any]] = [
        {"name": "🎚️ Level", "value": _safe_field(profile.get("level")), "inline": True},
        {"name": "🏆 Rank", "value": _safe_field(profile.get("rank")), "inline": True},
        {"name": "🔥 Streak", "value": _safe_field(profile.get("streak")), "inline": True},
        {"name": "🚪 Completed Rooms", "value": _safe_field(profile.get("completed_rooms")), "inline": True},
        {"name": "🏅 Badges", "value": _safe_field(profile.get("badges")), "inline": True},
    ]

    league = str(profile.get("league") or "").strip()
    if league and league != "N/A":
        fields.append({"name": "💎 League", "value": _safe_field(league), "inline": True})

    total_points = profile.get("total_points")
    if isinstance(total_points, int):
        fields.append({"name": "⭐ Points", "value": f"{total_points:,}", "inline": True})

    cap_score = profile.get("capability_score")
    if isinstance(cap_score, (int, float)):
        pov = str(profile.get("capability_pov") or "").strip()
        cap_label = f"{cap_score:.1f} ({pov})" if pov else f"{cap_score:.1f}"
        fields.append({"name": "⚡ Capability", "value": _safe_field(cap_label), "inline": True})

    country = str(profile.get("country") or "").strip()
    if country:
        fields.append({"name": "🌍 Country", "value": _safe_field(country), "inline": True})

    profile_embed: Dict[str, Any] = {
        "title": f"👤 TryHackMe Profile — {username}"[:256],
        "color": 0x1ABC9C,
        "fields": fields[:25],
        "timestamp": timestamp,
    }

    profile_url = profile.get("profile_url") or f"https://tryhackme.com/p/{username}"
    if _is_http_url(profile_url):
        profile_embed["url"] = profile_url

    avatar = profile.get("avatar")
    if _is_http_url(avatar):
        profile_embed["thumbnail"] = {"url": avatar}

    about = str(profile.get("about") or "").strip()
    if about:
        profile_embed["description"] = about[:400] + ("..." if len(about) > 400 else "")

    if profile.get("is_private"):
        profile_embed["footer"] = {"text": "⚠️ Perfil configurado como privado no TryHackMe"}

    # Embed 2: Salas concluídas
    room_details = data.get("completed_rooms_details") or []
    raw_rooms = data.get("completed_rooms") or []
    room_lines: List[str] = []

    if isinstance(room_details, list) and room_details:
        for item in room_details[:25]:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            if not title:
                continue
            diff = str(item.get("difficulty") or "").lower()
            emoji = DIFFICULTY_EMOJI.get(diff, "▪️")
            url = str(item.get("url") or "").strip()
            if _is_http_url(url):
                room_lines.append(f"{emoji} [{title}]({url})")
            else:
                room_lines.append(f"{emoji} {title}")
    elif isinstance(raw_rooms, list):
        for r_name in raw_rooms[:25]:
            if isinstance(r_name, dict):
                title = str(r_name.get("title") or r_name.get("name") or "").strip()
            else:
                title = str(r_name).strip()
            if title:
                room_lines.append(f"▪️ {title}")

    total_rooms_display = str(profile.get("completed_rooms") or len(raw_rooms))
    shown_rooms = len(room_lines)
    rooms_footer = (
        f"Exibindo {shown_rooms} salas • Total no perfil: {total_rooms_display}"
        if shown_rooms
        else f"Total no perfil: {total_rooms_display}"
    )

    rooms_embed: Dict[str, Any] = {
        "title": "🏁 Completed Rooms",
        "color": 0x3498DB,
        "description": _truncate_lines(room_lines, max_chars=1800),
        "footer": {"text": rooms_footer[:2048]},
        "timestamp": timestamp,
    }

    # Embed 3: Badges
    raw_badges = data.get("badges") or []
    badge_lines: List[str] = []
    if isinstance(raw_badges, list):
        for badge in raw_badges[:25]:
            if isinstance(badge, dict):
                b_name = str(badge.get("name") or badge.get("title") or "").strip()
                rarity = str(badge.get("rarity") or "").lower()
                pct = badge.get("rarity_percent")
                emoji = RARITY_EMOJI.get(rarity, "🏅")
                if b_name:
                    suffix = f" `({pct}%)`" if isinstance(pct, (int, float)) else ""
                    badge_lines.append(f"{emoji} **{b_name}**{suffix}")
            elif badge:
                badge_lines.append(f"🏅 **{str(badge).strip()}**")

    total_badges_display = str(profile.get("badges") or len(raw_badges))
    shown_badges = len(badge_lines)
    badges_footer = (
        f"Exibindo {shown_badges} badges • Total no perfil: {total_badges_display}"
        if shown_badges
        else f"Total no perfil: {total_badges_display}"
    )

    badges_embed: Dict[str, Any] = {
        "title": "🏅 Badges",
        "color": 0xF1C40F,
        "description": _truncate_lines(badge_lines, max_chars=1800),
        "footer": {"text": badges_footer[:2048]},
        "timestamp": timestamp,
    }

    return {
        "username": "THM Specter Tracker",
        "embeds": [profile_embed, rooms_embed, badges_embed],
    }


def send_webhook(data: Dict[str, Any], webhook_url: str, timeout: int = 15) -> bool:
    """Envia os embeds ao Webhook do Discord com validação e tratamento de rate-limit (429)."""
    import requests

    cleaned_url = (webhook_url or "").strip()
    if not cleaned_url:
        print("[INFO] Webhook do Discord não informado — envio ignorado.")
        return False

    if not is_valid_discord_webhook(cleaned_url):
        print("[ERRO] URL de Webhook do Discord inválida. Verifique a URL configurada.")
        return False

    try:
        payload = build_discord_payload(data)
    except ValueError as exc:
        print(f"[ERRO] Não foi possível montar o embed do Discord: {exc}")
        return False

    for attempt in range(2):
        try:
            resp = requests.post(cleaned_url, json=payload, timeout=timeout)
            if resp.status_code == 429 and attempt == 0:
                retry_after = 2.0
                try:
                    retry_after = float(resp.json().get("retry_after", 2.0))
                except Exception:
                    pass
                wait_s = min(max(retry_after, 0.5), 10.0)
                print(f"[AVISO] Rate-limit no Discord (429). Aguardando {wait_s:.1f}s...")
                time.sleep(wait_s)
                continue

            resp.raise_for_status()
            print(f"[OK] Embed enviado ao Discord com sucesso (HTTP {resp.status_code})!")
            return True
        except requests.RequestException as exc:
            detail = ""
            resp_obj = getattr(exc, "response", None)
            if resp_obj is not None and getattr(resp_obj, "text", None):
                detail = f" | Resposta: {resp_obj.text[:200]}"
            print(f"[ERRO] Falha ao enviar para o Webhook do Discord: {exc}{detail}")
            return False

    return False
