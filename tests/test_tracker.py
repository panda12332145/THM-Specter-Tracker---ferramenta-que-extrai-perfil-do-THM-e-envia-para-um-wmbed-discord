#!/usr/bin/env python3
"""Testes automatizados do THM Specter Tracker (100% offline com mocks)."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.bootstrap import ensure_dependencies
from src.collector import (
    BotChallengeError,
    ProfileNotFoundError,
    collect_all,
    collect_via_api_transport,
    collect_via_dom,
    fetch_paginated_badges,
    fetch_paginated_rooms,
    parse_api_profile,
)
from src.config import load_dotenv_file, normalize_username, parse_config
from src.discord_webhook import (
    build_discord_payload,
    is_valid_discord_webhook,
    send_webhook,
)
from src.storage import save_json


SAMPLE_API_PROFILE = {
    "status": "success",
    "data": {
        "avatar": "https://cdn-images.tryhackme.com/user-avatars/5ec914c35ec3f227230cc3a0.png",
        "username": "CyberOwl",
        "level": 21,
        "country": "gb",
        "about": "In the realm of cybersecurity, the wise owl sees all.",
        "totalPoints": 201226,
        "badgesNumber": 113,
        "completedRoomsNumber": 1331,
        "streak": 707,
        "largestStreak": 719,
        "rank": 11,
        "topPercentage": 1,
        "leagueTier": "ruby",
        "capabilityScore": {"value": 109.05, "pov": "purple"},
        "isPrivateProfile": False,
        "badgeImageURL": "https://tryhackme-badges.s3.amazonaws.com/CyberOwl.png",
        "dateSignUp": "2020-05-23T12:19:15.068Z",
    },
}


class TestConfigAndUsername(unittest.TestCase):
    def test_normalize_username_from_plain_and_urls(self):
        self.assertEqual(normalize_username("CyberOwl"), "CyberOwl")
        self.assertEqual(
            normalize_username("https://tryhackme.com/p/CyberOwl?tab=badges"),
            "CyberOwl",
        )
        self.assertEqual(normalize_username("tryhackme.com/p/panda_123/"), "panda_123")

    def test_normalize_username_rejects_invalid_input(self):
        with self.assertRaises(ValueError):
            normalize_username("CyberOwl; rm -rf /")
        with self.assertRaises(ValueError):
            normalize_username("nome com espaco")

    def test_dotenv_and_cli_parsing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env"
            env_path.write_text(
                'THM_USERNAME="TestUser"\n'
                "DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/123456/token_abc\n"
                "THM_MAX_ROOMS=120\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                loaded = load_dotenv_file(env_path)
                self.assertEqual(loaded["THM_USERNAME"], "TestUser")
                cfg = parse_config(argv=["--no-webhook"], interactive=False, dotenv_path=env_path)
                self.assertEqual(cfg.username, "TestUser")
                self.assertEqual(cfg.max_rooms, 120)
                self.assertTrue(cfg.no_webhook)
                self.assertEqual(cfg.webhook_url, "")


class TestCollectorParsingAndFallbacks(unittest.TestCase):
    def test_parse_api_profile_full(self):
        profile = parse_api_profile(SAMPLE_API_PROFILE, fallback_username="cyberowl")
        self.assertEqual(profile["username"], "CyberOwl")
        self.assertEqual(profile["level"], "21")
        self.assertEqual(profile["rank"], "#11 (Top 1%)")
        self.assertEqual(profile["streak"], "707 days (Max: 719)")
        self.assertEqual(profile["badges"], "113")
        self.assertEqual(profile["completed_rooms"], "1331")
        self.assertEqual(profile["league"], "Ruby")
        self.assertEqual(profile["total_points"], 201226)
        self.assertEqual(profile["capability_score"], 109.05)
        self.assertEqual(profile["country"], "GB")

    def test_parse_api_profile_not_found(self):
        with self.assertRaises(ProfileNotFoundError):
            parse_api_profile(
                {"status": "error", "message": "Profile not found"},
                fallback_username="ghost_user",
            )

    def test_pagination_rooms_and_badges(self):
        pages_rooms = {
            1: {
                "status": "success",
                "data": {
                    "docs": [
                        {"title": "Crack the hash", "code": "crackthehash", "difficulty": "easy"},
                        {"title": "Mr Robot CTF", "code": "mrrobot", "difficulty": "medium"},
                    ],
                    "hasNextPage": True,
                    "totalPages": 2,
                },
            },
            2: {
                "status": "success",
                "data": {
                    "docs": [
                        {"title": "Jurassic Park", "code": "jurassicpark", "difficulty": "hard"},
                    ],
                    "hasNextPage": False,
                    "totalPages": 2,
                },
            },
        }

        def fake_fetch_rooms(path: str):
            p = 2 if "page=2" in path else 1
            return pages_rooms[p]

        names, details = fetch_paginated_rooms(fake_fetch_rooms, "CyberOwl", max_rooms=10)
        self.assertEqual(names, ["Crack the hash", "Mr Robot CTF", "Jurassic Park"])
        self.assertEqual(details[0]["url"], "https://tryhackme.com/room/crackthehash")

        names_limited, _ = fetch_paginated_rooms(fake_fetch_rooms, "CyberOwl", max_rooms=2)
        self.assertEqual(len(names_limited), 2)

        def fake_fetch_badges(_path: str):
            return {
                "status": "success",
                "data": {
                    "docs": [
                        {
                            "name": "blue",
                            "title": "Blue",
                            "image": "https://assets.tryhackme.com/img/badges/blue.png",
                            "description": "Hacking into Windows via EternalBlue",
                            "rarityTier": "rare",
                            "rarityPercent": 9.6,
                        }
                    ],
                    "hasNextPage": False,
                    "totalPages": 1,
                },
            }

        badges = fetch_paginated_badges(fake_fetch_badges, "CyberOwl")
        self.assertEqual(len(badges), 1)
        self.assertEqual(badges[0]["name"], "Blue")
        self.assertEqual(badges[0]["rarity"], "rare")

    def test_collect_all_falls_back_to_browser_on_429_challenge(self):
        browser_result = (
            collect_via_api_transport(
                lambda path: (
                    SAMPLE_API_PROFILE
                    if "completed-rooms" not in path and "badges" not in path
                    else {"status": "success", "data": {"docs": [], "hasNextPage": False}}
                ),
                "CyberOwl",
            ),
            "api_browser",
        )
        with patch("src.collector.RequestsTransport") as mock_req_cls, patch(
            "src.collector.collect_via_browser", return_value=browser_result
        ) as mock_browser:
            mock_req_cls.return_value.fetch_json.side_effect = BotChallengeError("HTTP 429")
            result = collect_all("CyberOwl", force_browser=False)
            self.assertEqual(result["source"], "api_browser")
            self.assertEqual(result["profile"]["username"], "CyberOwl")
            mock_browser.assert_called_once()

    def test_collect_via_dom_nextjs_structure(self):
        """Garante que o fallback DOM extrai o título correto da sala (e não 'blue team')."""
        fake_page = MagicMock()

        body_loc = MagicMock()
        body_loc.inner_text.return_value = (
            "CyberOwl\n109\nCapability score\nRuby\nHighest league\n"
            "Top 1%\nRanking\n719\nHighest streak"
        )

        h1_loc = MagicMock()
        h1_loc.first.count.return_value = 1
        h1_loc.first.inner_text.return_value = "CyberOwl"

        avatar_loc = MagicMock()
        avatar_loc.first.count.return_value = 1
        avatar_loc.first.get_attribute.return_value = "https://cdn-images.tryhackme.com/user-avatars/x.png"

        badge_img = MagicMock()
        badge_img.get_attribute.side_effect = lambda attr: (
            "https://assets.tryhackme.com/img/badges/linux.png" if attr == "src" else "cat linux.txt"
        )
        badges_loc = MagicMock()
        badges_loc.all.return_value = [badge_img]

        room_link = MagicMock()
        room_link.get_attribute.return_value = "/room/crackthehash"
        strong_loc = MagicMock()
        strong_loc.first.count.return_value = 1
        strong_loc.first.inner_text.return_value = "Crack the hash"
        room_link.locator.return_value = strong_loc
        room_link.inner_text.return_value = "blue team\nEasy · 45 min\nCrack the hash\nCracking hashes"
        rooms_loc = MagicMock()
        rooms_loc.all.return_value = [room_link]

        def locator_router(sel: str):
            if sel == "body":
                return body_loc
            if sel == "h1":
                return h1_loc
            if "User profile photo" in sel:
                return avatar_loc
            if "badges" in sel:
                return badges_loc
            if "/room/" in sel:
                return rooms_loc
            empty = MagicMock()
            empty.first.count.return_value = 0
            empty.all.return_value = []
            return empty

        fake_page.locator.side_effect = locator_router
        res = collect_via_dom(fake_page, "CyberOwl")
        self.assertEqual(res["profile"]["username"], "CyberOwl")
        self.assertEqual(res["profile"]["rank"], "Top 1%")
        self.assertEqual(res["profile"]["league"], "Ruby")
        self.assertEqual(res["completed_rooms"], ["Crack the hash"])
        self.assertEqual(res["badges"][0]["name"], "cat linux.txt")


class TestDiscordWebhookAndStorage(unittest.TestCase):
    def test_webhook_url_validation(self):
        self.assertTrue(
            is_valid_discord_webhook("https://discord.com/api/webhooks/1234567890/AbCdEf_123-xyz")
        )
        self.assertTrue(
            is_valid_discord_webhook("https://discordapp.com/api/webhooks/999/Token123")
        )
        self.assertFalse(is_valid_discord_webhook("https://example.com/api/webhooks/123/abc"))
        self.assertFalse(is_valid_discord_webhook(""))

    def test_empty_profile_never_raises_keyerror(self):
        with self.assertRaises(ValueError):
            build_discord_payload({"profile": {}, "completed_rooms": [], "badges": []})

    def test_payload_omits_empty_thumbnail_and_respects_discord_limits(self):
        profile = parse_api_profile(SAMPLE_API_PROFILE, "CyberOwl")
        profile["avatar"] = None

        huge_rooms = [
            {
                "title": f"Room Extremamente Longa Número {i}",
                "code": f"room-{i}",
                "url": f"https://tryhackme.com/room/room-{i}",
                "difficulty": "hard",
            }
            for i in range(100)
        ]
        huge_badges = [
            {"name": f"Badge Especial de Segurança Ofensiva #{i}", "rarity": "epic", "rarity_percent": 0.5}
            for i in range(100)
        ]

        payload = build_discord_payload(
            {
                "timestamp": "2026-11-02T00:00:00+00:00",
                "profile": profile,
                "completed_rooms": [r["title"] for r in huge_rooms],
                "completed_rooms_details": huge_rooms,
                "badges": huge_badges,
            }
        )

        embeds = payload["embeds"]
        self.assertEqual(len(embeds), 3)
        self.assertNotIn("thumbnail", embeds[0])

        total_chars = 0
        for emb in embeds:
            total_chars += len(emb.get("title", "")) + len(emb.get("description", ""))
            total_chars += len(emb.get("footer", {}).get("text", ""))
            self.assertLessEqual(len(emb.get("description", "")), 4096)
            for field in emb.get("fields", []):
                self.assertIsInstance(field["value"], str)
                self.assertGreaterEqual(len(field["value"]), 1)
                self.assertLessEqual(len(field["value"]), 1024)
                total_chars += len(field["name"]) + len(field["value"])

        self.assertLess(total_chars, 6000)

    def test_send_webhook_handles_rate_limit_429_then_succeeds(self):
        ensure_dependencies(auto_install=True, install_browsers=False)
        profile = parse_api_profile(SAMPLE_API_PROFILE, "CyberOwl")
        sample_data = {
            "timestamp": "2026-11-02T00:00:00+00:00",
            "profile": profile,
            "completed_rooms": ["Crack the hash"],
            "completed_rooms_details": [],
            "badges": [{"name": "Blue"}],
        }

        resp_429 = MagicMock(status_code=429)
        resp_429.json.return_value = {"retry_after": 0.01}
        resp_204 = MagicMock(status_code=204)
        resp_204.raise_for_status.return_value = None

        with patch("requests.post", side_effect=[resp_429, resp_204]) as mock_post:
            ok = send_webhook(
                sample_data,
                "https://discord.com/api/webhooks/123456789/validTokenHere",
            )
            self.assertTrue(ok)
            self.assertEqual(mock_post.call_count, 2)

    def test_atomic_save_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "tryhackme_profile.json"
            sample = {"profile": {"username": "CyberOwl", "note": "Acentuação çãõ 🚀"}}
            written = save_json(sample, target)
            self.assertTrue(written.exists())
            self.assertFalse(target.with_name("tryhackme_profile.json.tmp").exists())
            reloaded = json.loads(written.read_text(encoding="utf-8"))
            self.assertEqual(reloaded["profile"]["note"], "Acentuação çãõ 🚀")


class TestMainEndToEnd(unittest.TestCase):
    def test_cli_end_to_end_success_and_error_handling(self):
        from src.main import main

        fake_collected = {
            "timestamp": "2026-11-02T00:00:00+00:00",
            "source": "api_http",
            "profile": parse_api_profile(SAMPLE_API_PROFILE, "CyberOwl"),
            "completed_rooms": ["Crack the hash", "Mr Robot CTF"],
            "completed_rooms_details": [
                {
                    "title": "Crack the hash",
                    "code": "crackthehash",
                    "url": "https://tryhackme.com/room/crackthehash",
                    "difficulty": "easy",
                }
            ],
            "badges": [{"name": "Blue", "rarity": "rare", "rarity_percent": 9.6}],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            out_json = Path(tmpdir) / "out.json"
            resp_204 = MagicMock(status_code=204)
            resp_204.raise_for_status.return_value = None

            with patch("src.collector.collect_all", return_value=fake_collected), patch(
                "requests.post", return_value=resp_204
            ) as mock_post:
                rc = main(
                    [
                        "--username",
                        "CyberOwl",
                        "--webhook",
                        "https://discord.com/api/webhooks/111222333/tokenAbc123",
                        "--output",
                        str(out_json),
                    ]
                )
                self.assertEqual(rc, 0)
                self.assertTrue(out_json.exists())
                mock_post.assert_called_once()

            # Quando o perfil não existe, retorna código 1 sem levantar KeyError
            missing_json = Path(tmpdir) / "should_not_exist.json"
            with patch(
                "src.collector.collect_all",
                side_effect=ProfileNotFoundError("Perfil inexistente"),
            ):
                rc_err = main(
                    [
                        "--username",
                        "GhostUser999",
                        "--no-webhook",
                        "--output",
                        str(missing_json),
                    ]
                )
                self.assertEqual(rc_err, 1)
                self.assertFalse(missing_json.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
