"""Coletor resiliente de perfis públicos do TryHackMe em 3 camadas:
1. API pública oficial v2 via HTTP (requests) — rápida e paginada
2. API pública oficial v2 dentro do contexto real do Chromium (Playwright) — contorna desafios Vercel/Cloudflare (HTTP 429/403)
3. Extração direta do novo DOM Next.js do TryHackMe via Playwright — fallback caso rotas de API mudem
"""

from __future__ import annotations

import json
import re
import time
import urllib.parse
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.bootstrap import ensure_playwright_chromium

THM_BASE = "https://tryhackme.com"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


class CollectorError(Exception):
    """Erro genérico durante a coleta no TryHackMe."""


class ProfileNotFoundError(CollectorError):
    """Perfil inexistente no TryHackMe."""


class BotChallengeError(CollectorError):
    """Requisição bloqueada por desafio anti-bot (HTTP 403/429/503)."""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_positive_int(value: Any) -> Optional[int]:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, float):
        return int(value) if value > 0 else None
    if isinstance(value, str):
        cleaned = value.strip().lstrip("#").replace(",", "").replace(".", "")
        if cleaned.isdigit():
            parsed = int(cleaned)
            return parsed if parsed > 0 else None
    return None


def _format_rank(rank: Any, top_percentage: Any) -> str:
    rank_int = _parse_positive_int(rank)
    has_pct = (
        isinstance(top_percentage, (int, float))
        and not isinstance(top_percentage, bool)
        and 0 < top_percentage <= 100
    )
    pct_str = f"Top {top_percentage}%" if has_pct else ""

    if rank_int is not None and pct_str:
        return f"#{rank_int:,} ({pct_str})"
    if rank_int is not None:
        return f"#{rank_int:,}"
    if isinstance(rank, str) and rank.strip() and rank.strip() != "0":
        return f"{rank.strip()} ({pct_str})" if pct_str else rank.strip()
    if pct_str:
        return pct_str
    return "Unranked"


def _format_streak(streak: Any, largest_streak: Any = None) -> str:
    cur = streak if isinstance(streak, int) and not isinstance(streak, bool) and streak >= 0 else None
    best = (
        largest_streak
        if isinstance(largest_streak, int) and not isinstance(largest_streak, bool) and largest_streak >= 0
        else None
    )

    if cur is not None:
        unit = "day" if cur == 1 else "days"
        base = f"{cur} {unit}"
        if best is not None and best > cur:
            return f"{base} (Max: {best})"
        return base
    if best is not None:
        unit = "day" if best == 1 else "days"
        return f"Max: {best} {unit}"
    return "N/A"


def parse_api_profile(payload: Dict[str, Any], fallback_username: str) -> Dict[str, Any]:
    """Valida e normaliza a resposta de /api/v2/public-profile."""
    if not isinstance(payload, dict):
        raise CollectorError("Resposta inesperada da API de perfil do TryHackMe.")

    if payload.get("status") == "error":
        msg = str(payload.get("message") or "Erro desconhecido")
        if "not found" in msg.lower():
            raise ProfileNotFoundError(
                f"Perfil '{fallback_username}' não encontrado no TryHackMe "
                f"(atenção: o username diferencia maiúsculas e minúsculas)."
            )
        raise CollectorError(f"API do TryHackMe retornou erro: {msg}")

    data = payload.get("data")
    if not isinstance(data, dict) or not data:
        raise ProfileNotFoundError(
            f"Perfil '{fallback_username}' não retornou dados públicos no TryHackMe."
        )

    username = str(data.get("username") or fallback_username).strip()
    is_private = bool(data.get("isPrivateProfile", False))
    avatar = data.get("avatar") or None
    if isinstance(avatar, str):
        avatar = avatar.strip() or None

    level_val = data.get("level")
    level_str = str(level_val) if level_val is not None and level_val != "" else "N/A"

    badges_num = data.get("badgesNumber")
    badges_str = str(badges_num) if badges_num is not None else "N/A"

    rooms_num = data.get("completedRoomsNumber")
    rooms_str = str(rooms_num) if rooms_num is not None else "N/A"

    league_raw = str(data.get("leagueTier") or "").strip()
    league_str = league_raw.capitalize() if league_raw else "Unranked"

    cap_raw = data.get("capabilityScore")
    cap_value: Optional[float] = None
    cap_pov: str = ""
    if isinstance(cap_raw, dict):
        raw_val = cap_raw.get("value")
        if isinstance(raw_val, (int, float)) and not isinstance(raw_val, bool):
            cap_value = round(float(raw_val), 2)
        cap_pov = str(cap_raw.get("pov") or "").strip()

    total_points = data.get("totalPoints")
    points_int = (
        int(total_points)
        if isinstance(total_points, (int, float)) and not isinstance(total_points, bool)
        else None
    )

    return {
        "username": username,
        "avatar": avatar,
        "level": level_str,
        "rank": _format_rank(data.get("rank"), data.get("topPercentage")),
        "raw_rank": _parse_positive_int(data.get("rank")),
        "top_percentage": data.get("topPercentage"),
        "total_points": points_int,
        "league": league_str,
        "badges": badges_str,
        "streak": _format_streak(data.get("streak"), data.get("largestStreak")),
        "completed_rooms": rooms_str,
        "capability_score": cap_value,
        "capability_pov": cap_pov,
        "country": str(data.get("country") or "").upper(),
        "about": str(data.get("about") or "").strip(),
        "is_private": is_private,
        "profile_url": f"{THM_BASE}/p/{urllib.parse.quote(username)}",
        "badge_image_url": str(data.get("badgeImageURL") or "").strip() or None,
        "date_signup": str(data.get("dateSignUp") or "").strip() or None,
    }


def fetch_paginated_rooms(
    fetch_json: Callable[[str], Dict[str, Any]],
    username: str,
    max_rooms: int = 500,
    page_size: int = 100,
) -> Tuple[List[str], List[Dict[str, Any]]]:
    """Busca salas concluídas paginando /api/v2/public-profile/completed-rooms."""
    room_names: List[str] = []
    room_details: List[Dict[str, Any]] = []
    seen_codes: set[str] = set()

    encoded_user = urllib.parse.quote(username)
    page = 1

    while True:
        limit = page_size
        if max_rooms > 0:
            remaining = max_rooms - len(room_names)
            if remaining <= 0:
                break
            limit = min(page_size, max(16, remaining))

        path = f"/api/v2/public-profile/completed-rooms?username={encoded_user}&limit={limit}&page={page}"
        payload = fetch_json(path)
        if not isinstance(payload, dict) or payload.get("status") != "success":
            break

        data = payload.get("data") or {}
        docs = data.get("docs") if isinstance(data, dict) else None
        if not isinstance(docs, list) or not docs:
            break

        added_in_page = 0
        for doc in docs:
            if not isinstance(doc, dict):
                continue
            title = str(doc.get("title") or doc.get("code") or "").strip()
            code = str(doc.get("code") or title).strip()
            if not title or code in seen_codes:
                continue

            seen_codes.add(code)
            room_names.append(title)
            room_details.append(
                {
                    "title": title,
                    "code": code,
                    "url": f"{THM_BASE}/room/{urllib.parse.quote(code)}" if code else "",
                    "difficulty": str(doc.get("difficulty") or "").strip(),
                    "type": str(doc.get("type") or "").strip(),
                    "free": bool(doc.get("freeToUse", False)),
                }
            )
            added_in_page += 1
            if max_rooms > 0 and len(room_names) >= max_rooms:
                break

        has_next = bool(data.get("hasNextPage")) if isinstance(data, dict) else False
        total_pages = data.get("totalPages") if isinstance(data, dict) else None
        if not has_next or added_in_page == 0:
            break
        if isinstance(total_pages, int) and page >= total_pages:
            break

        page += 1
        time.sleep(0.15)

    return room_names, room_details


def fetch_paginated_badges(
    fetch_json: Callable[[str], Dict[str, Any]],
    username: str,
    page_size: int = 100,
) -> List[Dict[str, Any]]:
    """Busca todos os badges conquistados paginando /api/v2/public-profile/badges."""
    badges: List[Dict[str, Any]] = []
    seen: set[str] = set()

    encoded_user = urllib.parse.quote(username)
    page = 1

    while True:
        path = f"/api/v2/public-profile/badges?username={encoded_user}&page={page}&limit={page_size}"
        payload = fetch_json(path)
        if not isinstance(payload, dict) or payload.get("status") != "success":
            break

        data = payload.get("data")
        if isinstance(data, dict):
            docs = data.get("docs") or []
            has_next = bool(data.get("hasNextPage"))
            total_pages = data.get("totalPages")
        elif isinstance(data, list):
            docs = data
            has_next = False
            total_pages = 1
        else:
            break

        if not isinstance(docs, list) or not docs:
            break

        added_in_page = 0
        for doc in docs:
            if not isinstance(doc, dict):
                continue
            title = str(doc.get("title") or doc.get("name") or "").strip()
            slug = str(doc.get("name") or title).strip()
            if not title or slug in seen:
                continue

            seen.add(slug)
            rarity_pct = doc.get("rarityPercent")
            badges.append(
                {
                    "name": title,
                    "slug": slug,
                    "icon": str(doc.get("image") or "").strip() or None,
                    "description": str(doc.get("description") or title).strip(),
                    "rarity": str(doc.get("rarityTier") or "").strip(),
                    "rarity_percent": (
                        round(float(rarity_pct), 2)
                        if isinstance(rarity_pct, (int, float)) and not isinstance(rarity_pct, bool)
                        else None
                    ),
                }
            )
            added_in_page += 1

        if not has_next or added_in_page == 0:
            break
        if isinstance(total_pages, int) and page >= total_pages:
            break

        page += 1
        time.sleep(0.15)

    return badges


def collect_via_api_transport(
    fetch_json: Callable[[str], Dict[str, Any]],
    username: str,
    max_rooms: int = 500,
) -> Dict[str, Any]:
    """Executa coleta completa (perfil + salas + badges) usando qualquer transporte JSON."""
    encoded_user = urllib.parse.quote(username)
    profile_payload = fetch_json(f"/api/v2/public-profile?username={encoded_user}")
    profile = parse_api_profile(profile_payload, fallback_username=username)
    canonical_username = profile["username"]

    if profile.get("is_private"):
        print(f"[AVISO] O perfil '{canonical_username}' está configurado como privado no TryHackMe.")
        return {
            "profile": profile,
            "completed_rooms": [],
            "completed_rooms_details": [],
            "badges": [],
        }

    try:
        rooms, room_details = fetch_paginated_rooms(
            fetch_json, canonical_username, max_rooms=max_rooms
        )
    except CollectorError as exc:
        print(f"[AVISO] Não foi possível paginar salas concluídas ({exc}).")
        rooms, room_details = [], []

    try:
        badges = fetch_paginated_badges(fetch_json, canonical_username)
    except CollectorError as exc:
        print(f"[AVISO] Não foi possível paginar badges ({exc}).")
        badges = []

    return {
        "profile": profile,
        "completed_rooms": rooms,
        "completed_rooms_details": room_details,
        "badges": badges,
    }


class RequestsTransport:
    """Transporte HTTP direto via requests.Session."""

    def __init__(self, username: str, timeout: int = 20) -> None:
        import requests

        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": DEFAULT_USER_AGENT,
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "en-US,en;q=0.9,pt-BR;q=0.8",
                "Referer": f"{THM_BASE}/p/{urllib.parse.quote(username)}",
            }
        )

    def fetch_json(self, endpoint_path: str) -> Dict[str, Any]:
        import requests

        url = f"{THM_BASE}{endpoint_path}"
        try:
            resp = self.session.get(url, timeout=self.timeout)
        except requests.RequestException as exc:
            raise CollectorError(f"Falha de conexão HTTP em {endpoint_path}: {exc}") from exc

        if resp.status_code == 404:
            try:
                body = resp.json()
                if isinstance(body, dict) and "not found" in str(body.get("message", "")).lower():
                    raise ProfileNotFoundError("Perfil não encontrado no TryHackMe.")
            except ValueError:
                pass
            raise ProfileNotFoundError(f"Recurso não encontrado (HTTP 404): {endpoint_path}")

        if resp.status_code in (403, 429, 503) or resp.headers.get("x-vercel-mitigated"):
            raise BotChallengeError(
                f"Proteção anti-bot ativa (HTTP {resp.status_code}) em {endpoint_path}"
            )

        if resp.status_code >= 500:
            raise CollectorError(f"Erro no servidor TryHackMe (HTTP {resp.status_code})")

        content_type = (resp.headers.get("content-type") or "").lower()
        text = resp.text or ""
        if "json" not in content_type and text.lstrip().startswith("<"):
            raise BotChallengeError("Resposta HTML recebida em vez de JSON (desafio anti-bot).")

        try:
            return resp.json()
        except ValueError as exc:
            raise CollectorError("Resposta inválida (não-JSON) recebida do TryHackMe.") from exc


def _launch_chromium_with_auto_install(playwright_instance: Any, headless: bool = True) -> Any:
    """Inicia o Chromium e instala automaticamente o binário caso esteja ausente/desatualizado."""
    launch_kwargs = {
        "headless": headless,
        "args": ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
    }
    try:
        return playwright_instance.chromium.launch(**launch_kwargs)
    except Exception as exc:
        msg = str(exc)
        if "Executable doesn't exist" in msg or "playwright install" in msg.lower():
            if ensure_playwright_chromium():
                return playwright_instance.chromium.launch(**launch_kwargs)
        raise


def collect_via_dom(page: Any, username: str) -> Dict[str, Any]:
    """Camada 3: Extrai perfil, salas e badges do DOM Next.js atual do TryHackMe."""
    body_text = ""
    try:
        body_text = page.locator("body").inner_text(timeout=10000)
    except Exception:
        pass

    if "404" in body_text and ("page not found" in body_text.lower() or "not exist" in body_text.lower()):
        raise ProfileNotFoundError(f"Perfil '{username}' não encontrado no TryHackMe.")

    dom_username = username
    try:
        h1 = page.locator("h1").first
        if h1.count() > 0:
            txt = h1.inner_text(timeout=3000).strip()
            if txt and len(txt) <= 64:
                dom_username = txt
    except Exception:
        pass

    avatar: Optional[str] = None
    for selector in (
        "img[alt*='User profile photo']",
        "img[aria-label='User avatar']",
        "img[src*='user-avatars']",
        "img[alt*='avatar' i]",
    ):
        try:
            loc = page.locator(selector).first
            if loc.count() > 0:
                src = loc.get_attribute("src")
                if src:
                    avatar = src if src.startswith("http") else f"{THM_BASE}{src}"
                    break
        except Exception:
            continue

    rank_match = re.search(r"(Top\s+\d+%|#[\d,]+)\s*\n*\s*Ranking", body_text, re.IGNORECASE)
    streak_match = re.search(r"(\d[\d,]*)\s*\n*\s*(?:Highest\s+)?streak", body_text, re.IGNORECASE)
    league_match = re.search(r"([A-Za-z]+)\s*\n*\s*Highest\s+league", body_text, re.IGNORECASE)
    cap_match = re.search(r"(\d+(?:\.\d+)?)\s*\n*\s*Capability\s+score", body_text, re.IGNORECASE)
    level_match = re.search(r"Level\s*(\d+|\[0x[0-9a-fA-F]+\])", body_text, re.IGNORECASE)

    # Coleta badges visíveis
    badges: List[Dict[str, Any]] = []
    seen_badges: set[str] = set()
    try:
        badge_imgs = page.locator("img[src*='/badges/'], img[src*='badges']").all()
        for img in badge_imgs:
            try:
                src = img.get_attribute("src") or ""
                alt = (img.get_attribute("alt") or "").strip()
                if not alt or alt in seen_badges:
                    continue
                seen_badges.add(alt)
                full_src = src if src.startswith("http") else f"{THM_BASE}{src}"
                badges.append(
                    {
                        "name": alt,
                        "slug": alt.lower().replace(" ", "-"),
                        "icon": full_src or None,
                        "description": alt,
                        "rarity": "",
                        "rarity_percent": None,
                    }
                )
            except Exception:
                continue
    except Exception:
        pass

    # Coleta salas visíveis no novo layout Next.js (evitando capturar 'red team' / 'blue team')
    rooms: List[str] = []
    room_details: List[Dict[str, Any]] = []
    seen_rooms: set[str] = set()
    ignored_prefixes = {"red team", "blue team", "purple team", "show all", "see more"}
    difficulty_pattern = re.compile(r"^(easy|medium|hard|info|insane)\s*·", re.IGNORECASE)

    try:
        room_links = page.locator("a[href*='/room/']").all()
        for link in room_links:
            try:
                href = link.get_attribute("href") or ""
                code = href.rstrip("/").split("/room/")[-1].split("?")[0].strip()
                title = ""

                strong = link.locator("strong, b, h3, h4").first
                if strong.count() > 0:
                    title = strong.inner_text(timeout=1500).strip()

                if not title:
                    lines = [ln.strip() for ln in link.inner_text(timeout=1500).splitlines() if ln.strip()]
                    for ln in lines:
                        if ln.lower() in ignored_prefixes or difficulty_pattern.match(ln):
                            continue
                        title = ln
                        break

                if title and title not in seen_rooms:
                    seen_rooms.add(title)
                    rooms.append(title)
                    room_details.append(
                        {
                            "title": title,
                            "code": code or title,
                            "url": f"{THM_BASE}/room/{code}" if code else "",
                            "difficulty": "",
                            "type": "",
                            "free": False,
                        }
                    )
            except Exception:
                continue
    except Exception:
        pass

    profile = {
        "username": dom_username,
        "avatar": avatar,
        "level": level_match.group(1) if level_match else "N/A",
        "rank": rank_match.group(1).strip() if rank_match else "N/A",
        "raw_rank": None,
        "top_percentage": None,
        "total_points": None,
        "league": league_match.group(1).capitalize() if league_match else "N/A",
        "badges": str(len(badges)) if badges else "N/A",
        "streak": f"{streak_match.group(1)} days" if streak_match else "N/A",
        "completed_rooms": str(len(rooms)) if rooms else "N/A",
        "capability_score": float(cap_match.group(1)) if cap_match else None,
        "capability_pov": "",
        "country": "",
        "about": "",
        "is_private": False,
        "profile_url": f"{THM_BASE}/p/{urllib.parse.quote(dom_username)}",
        "badge_image_url": None,
        "date_signup": None,
    }

    return {
        "profile": profile,
        "completed_rooms": rooms,
        "completed_rooms_details": room_details,
        "badges": badges,
    }


def collect_via_browser(
    username: str,
    max_rooms: int = 500,
    headless: bool = True,
    timeout_ms: int = 60000,
) -> Tuple[Dict[str, Any], str]:
    """Camadas 2 e 3 via Playwright Chromium."""
    from playwright.sync_api import sync_playwright

    profile_url = f"{THM_BASE}/p/{urllib.parse.quote(username)}"

    with sync_playwright() as p:
        browser = _launch_chromium_with_auto_install(p, headless=headless)
        try:
            context = browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent=DEFAULT_USER_AGENT,
                java_script_enabled=True,
            )
            page = context.new_page()
            page.goto(profile_url, wait_until="domcontentloaded", timeout=timeout_ms)

            # Aguarda estabilização inicial (sem travar em conexões persistentes de analytics/Intercom)
            try:
                page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                page.wait_for_timeout(2000)

            def browser_fetch_json(endpoint_path: str) -> Dict[str, Any]:
                result = page.evaluate(
                    """async (url) => {
                        const r = await fetch(url, {
                            headers: { "accept": "application/json" },
                            credentials: "same-origin"
                        });
                        return { status: r.status, text: await r.text() };
                    }""",
                    endpoint_path,
                )
                status = result.get("status", 0)
                text = result.get("text", "")
                if status == 404:
                    raise ProfileNotFoundError(f"Perfil '{username}' não encontrado (HTTP 404).")
                if status != 200:
                    raise CollectorError(f"Fetch no navegador retornou HTTP {status} para {endpoint_path}")
                try:
                    return json.loads(text)
                except ValueError as exc:
                    raise CollectorError("Fetch no navegador retornou corpo não-JSON.") from exc

            try:
                collected = collect_via_api_transport(
                    browser_fetch_json, username=username, max_rooms=max_rooms
                )
                return collected, "api_browser"
            except ProfileNotFoundError:
                raise
            except Exception as api_exc:
                print(
                    f"[AVISO] API via navegador indisponível ({api_exc}). "
                    "Ativando extração direta do DOM Next.js..."
                )
                collected = collect_via_dom(page, username=username)
                return collected, "dom_browser"
        finally:
            browser.close()


def collect_all(
    username: str,
    max_rooms: int = 500,
    force_browser: bool = False,
    headless: bool = True,
    timeout_ms: int = 60000,
) -> Dict[str, Any]:
    """Orquestra a coleta completa (Camada 1 HTTP -> Camada 2/3 Navegador)."""
    collected: Optional[Dict[str, Any]] = None
    source = "api_http"

    if not force_browser:
        try:
            transport = RequestsTransport(username=username, timeout=max(10, timeout_ms // 1000))
            collected = collect_via_api_transport(
                transport.fetch_json, username=username, max_rooms=max_rooms
            )
            source = "api_http"
        except ProfileNotFoundError:
            raise
        except BotChallengeError as exc:
            print(
                f"[INFO] {exc} — alternando automaticamente para coleta via navegador Chromium..."
            )
        except CollectorError as exc:
            print(
                f"[AVISO] Falha na coleta HTTP direta ({exc}) — tentando fallback via navegador Chromium..."
            )

    if collected is None:
        collected, source = collect_via_browser(
            username=username,
            max_rooms=max_rooms,
            headless=headless,
            timeout_ms=timeout_ms,
        )

    return {
        "timestamp": utc_now_iso(),
        "source": source,
        "profile": collected["profile"],
        "completed_rooms": collected["completed_rooms"],
        "completed_rooms_details": collected.get("completed_rooms_details", []),
        "badges": collected["badges"],
    }
