from playwright.sync_api import sync_playwright
from datetime import datetime, timezone
import requests
import json
import time

USERNAME = "CyberOwl"
WEBHOOK_URL = "https://discord.com/api/webhooks/1467613978464358684/PlMhaMx0ZS8DD_U0II_E0ukS9e1L8cNW5x9DmKk8_0iS-um9N6r2GcfLd2hefNtBsfC8"
BASE_URL = f"https://tryhackme.com/p/{USERNAME}"


def now():
    return datetime.now(timezone.utc).isoformat()


def extract_stat_by_label(page, label):
    """Extract statistics based on label using the new HTML structure"""
    try:
        # Wait a bit for page to fully load
        page.wait_for_timeout(2000)
        
        # Find the statistic box containing the label
        # First, find all statistic boxes
        stat_boxes = page.locator("[data-sentry-element='StyledStatisticBox']").all()
        
        for box in stat_boxes:
            # Check if this box contains our label
            try:
                label_element = box.locator(f"text='{label}'").first
                if label_element and label_element.is_visible():
                    # Find the number within this box
                    number_element = box.locator("[data-sentry-element='StyledStatisticsBoxNumber']").first
                    if number_element:
                        return number_element.inner_text().strip()
            except:
                continue
        
        # Alternative approach: direct CSS selector
        number = page.locator(f"div:has-text('{label}') ~ div [data-sentry-element='StyledStatisticsBoxNumber']").first
        if number:
            return number.inner_text().strip()
        
        return "N/A"
    except Exception as e:
        print(f"Error extracting {label}: {e}")
        return "N/A"


def extract_all_stats_directly(page):
    """Extract all statistics directly from their elements"""
    stats = {}
    
    try:
        # Get all statistic number elements
        number_elements = page.locator("[data-sentry-element='StyledStatisticsBoxNumber']").all()
        
        # Get all statistic text elements
        text_elements = page.locator("[data-sentry-element='StyledStatisticsBoxText']").all()
        
        # Match them up (they should be in the same order in the HTML)
        for i in range(min(len(text_elements), len(number_elements))):
            try:
                label = text_elements[i].inner_text().strip()
                value = number_elements[i].inner_text().strip()
                stats[label.lower()] = value
            except:
                continue
        
        return stats
    except Exception as e:
        print(f"Error extracting stats directly: {e}")
        return {}


def collect_profile(page):
    """Collect profile information"""
    page.goto(BASE_URL, timeout=60000)
    
    # Wait for page to load
    page.wait_for_selector(f"text={USERNAME}", timeout=60000)
    page.wait_for_selector("[data-sentry-element='StyledStatisticBox']", timeout=10000)
    
    # Give extra time for dynamic content
    page.wait_for_timeout(3000)
    
    profile = {}
    profile["username"] = USERNAME

    # Avatar
    try:
        avatar = page.locator("img[aria-label='User avatar']").first
        if avatar:
            profile["avatar"] = avatar.get_attribute("src")
        else:
            avatar = page.locator("img[alt*='avatar'], img[alt*='Avatar']").first
            profile["avatar"] = avatar.get_attribute("src") if avatar else None
    except:
        profile["avatar"] = None

    # Level - using the data-testid attribute from your HTML
    try:
        level_element = page.locator("[data-testid='level']").first
        if level_element:
            profile["level"] = level_element.inner_text().strip()
        else:
            # Fallback: try to find by data-sentry-element
            level_element = page.locator("[data-sentry-element='StyledLevelText']").first
            if level_element:
                profile["level"] = level_element.inner_text().strip()
            else:
                # Additional fallback: look for level text
                level_elements = page.locator("text=/Level.*/, text=/level.*/, text=/.*Level.*/").all()
                for elem in level_elements:
                    text = elem.inner_text().strip()
                    if "level" in text.lower() and len(text) < 50:
                        profile["level"] = text
                        break
                else:
                    profile["level"] = "N/A"
    except Exception as e:
        print(f"Error extracting level: {e}")
        profile["level"] = "N/A"

    # Extract all statistics at once
    stats = extract_all_stats_directly(page)
    
    # Map the stats to our profile
    profile["rank"] = stats.get("rank", "N/A")
    profile["badges"] = stats.get("badges", "N/A")
    profile["streak"] = stats.get("streak", "N/A")
    profile["completed_rooms"] = stats.get("completed rooms", "N/A")
    
    # Fallback to individual extraction if direct method failed
    if profile["rank"] == "N/A":
        profile["rank"] = extract_stat_by_label(page, "Rank")
    if profile["badges"] == "N/A":
        profile["badges"] = extract_stat_by_label(page, "Badges")
    if profile["streak"] == "N/A":
        profile["streak"] = extract_stat_by_label(page, "Streak")
    if profile["completed_rooms"] == "N/A":
        profile["completed_rooms"] = extract_stat_by_label(page, "Completed rooms")
    
    return profile


def collect_completed_rooms(page):
    """Collect completed rooms - simplified approach"""
    page.goto(f"{BASE_URL}?tab=completed-rooms", timeout=60000)
    
    # Wait for rooms to load
    page.wait_for_selector("a[href*='/room/']", timeout=10000)
    page.wait_for_timeout(2000)
    
    rooms = []
    seen = set()
    
    # Simple approach: find all room links
    try:
        room_links = page.locator("a[href*='/room/']").all()
        for link in room_links:
            try:
                # Get text content
                text = link.inner_text().strip()
                if text and text not in seen:
                    # Clean up - take first meaningful line
                    lines = [line.strip() for line in text.split('\n') if line.strip()]
                    if lines:
                        room_name = lines[0]
                        if len(room_name) > 1 and room_name not in seen:
                            rooms.append(room_name)
                            seen.add(room_name)
            except:
                continue
    except:
        pass
    
    return list(rooms)


def collect_badges(page):
    """Collect badges from the badges tab"""
    page.goto(f"{BASE_URL}?tab=badges", timeout=60000)
    
    # Wait for badges to load
    page.wait_for_selector("[data-testid='badge']", timeout=10000)
    page.wait_for_timeout(2000)
    
    badges = []
    seen = set()
    
    try:
        # Find all badge elements using data-testid
        badge_elements = page.locator("[data-testid='badge']").all()
        
        for badge in badge_elements:
            try:
                # Get the image element
                img = badge.locator("img").first
                if img:
                    src = img.get_attribute("src")
                    alt = img.get_attribute("alt")
                    
                    # Get the badge title from the p element with data-content="title"
                    title_element = badge.locator("p[data-content='title']").first
                    if title_element:
                        title = title_element.inner_text().strip()
                    else:
                        # Fallback: use alt text or find any p element
                        title = alt if alt else "Unknown Badge"
                    
                    # Only add if we haven't seen this badge
                    if title and title not in seen:
                        badges.append({
                            "name": title,
                            "icon": src,
                            "description": alt if alt else title
                        })
                        seen.add(title)
                        
            except Exception as e:
                print(f"Error processing badge: {e}")
                continue
        
        # If no badges found with data-testid, try alternative selectors
        if not badges:
            # Try looking for badge articles
            badge_articles = page.locator("article:has(img[src*='badges'])").all()
            for article in badge_articles:
                try:
                    img = article.locator("img").first
                    if img:
                        alt = img.get_attribute("alt")
                        src = img.get_attribute("src")
                        
                        # Try to get title
                        title_elements = article.locator("p").all()
                        title = alt
                        for p in title_elements:
                            text = p.inner_text().strip()
                            if text and len(text) < 50:  # Likely a title
                                title = text
                                break
                        
                        if title and title not in seen:
                            badges.append({
                                "name": title,
                                "icon": src,
                                "description": alt if alt else title
                            })
                            seen.add(title)
                except:
                    continue
    
    except Exception as e:
        print(f"Error collecting badges: {e}")
    
    return badges


def save_json(data):
    """Save data to JSON file"""
    with open("tryhackme_profile.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def send_webhook(data):
    """Send data to Discord webhook"""
    embeds = []

    # Profile embed
    embeds.append({
        "title": f"👤 TryHackMe Profile — {data['profile']['username']}",
        "thumbnail": {"url": data["profile"]["avatar"]} if data["profile"]["avatar"] else {},
        "color": 0x1ABC9C,
        "fields": [
            {"name": "Level", "value": data["profile"]["level"], "inline": True},
            {"name": "Rank", "value": data["profile"]["rank"], "inline": True},
            {"name": "Badges", "value": data["profile"]["badges"], "inline": True},
            {"name": "Streak", "value": data["profile"]["streak"], "inline": True},
            {"name": "Completed Rooms", "value": data["profile"]["completed_rooms"], "inline": True},
        ],
        "timestamp": now()
    })

    # Completed rooms embed
    rooms_text = "\n".join(data["completed_rooms"][:25]) if data["completed_rooms"] else "None"
    embeds.append({
        "title": "🏁 Completed Rooms",
        "color": 0x3498DB,
        "description": rooms_text[:2048] if len(rooms_text) > 2048 else rooms_text,
        "footer": {"text": f"Total: {len(data['completed_rooms'])}"},
        "timestamp": now()
    })

    # Badges embed
    badges_text = "\n".join(b["name"] for b in data["badges"][:25]) if data["badges"] else "None"
    embeds.append({
        "title": "🏅 Badges",
        "color": 0xF1C40F,
        "description": badges_text[:2048] if len(badges_text) > 2048 else badges_text,
        "footer": {"text": f"Total: {len(data['badges'])}"},
        "timestamp": now()
    })

    try:
        r = requests.post(WEBHOOK_URL, json={"embeds": embeds})
        r.raise_for_status()
        print(f"[OK] Webhook sent successfully: {r.status_code}")
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] Failed to send webhook: {e}")


def main():
    """Main function"""
    data = {
        "timestamp": now(),
        "profile": {},
        "completed_rooms": [],
        "badges": []
    }

    with sync_playwright() as p:
        # Launch browser
        browser = p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage']
        )
        
        # Create context
        context = browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            java_script_enabled=True
        )
        
        page = context.new_page()

        try:
            print("Collecting profile...")
            data["profile"] = collect_profile(page)
            print(f"Profile collected:")
            print(f"  Level: {data['profile']['level']}")
            print(f"  Rank: {data['profile']['rank']}")
            print(f"  Badges: {data['profile']['badges']}")
            print(f"  Streak: {data['profile']['streak']}")
            print(f"  Completed rooms: {data['profile']['completed_rooms']}")
            
            print("Collecting completed rooms...")
            data["completed_rooms"] = collect_completed_rooms(page)
            print(f"Found {len(data['completed_rooms'])} rooms")
            if data["completed_rooms"]:
                print(f"First few: {data['completed_rooms'][:3]}")
            
            print("Collecting badges...")
            data["badges"] = collect_badges(page)
            print(f"Found {len(data['badges'])} badges")
            if data["badges"]:
                print(f"Badges found: {[b['name'] for b in data['badges']]}")
            
        except Exception as e:
            print(f"[ERROR] Error during collection: {e}")
            import traceback
            traceback.print_exc()
        finally:
            browser.close()

    # Save and send
    save_json(data)
    print(f"Data saved to tryhackme_profile.json")
    
    send_webhook(data)
    
    print("[OK] Collection complete!")


if __name__ == "__main__":
    main()