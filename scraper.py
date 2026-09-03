import os
import csv
import json
import time
import requests
import subprocess
from datetime import datetime, timezone, timedelta
from apify_client import ApifyClient

# --- CONFIGURACIÓ ---
APIFY_TOKEN = os.getenv('APIFY_TOKEN')
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
CHAT_ID = os.getenv('CHAT_ID')
GITHUB_REPOSITORY = os.getenv('GITHUB_REPOSITORY')

DB_FILE = 'processed_videos.json'
ACCOUNTS_FILE = 'accounts.csv'
BACKUP_CSV = 'backup_reels.csv'
QUEUE_FILE = 'today_queue.json'

def load_accounts():
    if not os.path.exists(ACCOUNTS_FILE):
        return []
    with open(ACCOUNTS_FILE, mode='r', encoding='utf-8') as f:
        return [line.strip() for line in f if "instagram.com" in line]

def load_backup_csv():
    if not os.path.exists(BACKUP_CSV):
        return []
    rows = []
    with open(BACKUP_CSV, mode='r', newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows

def save_backup_csv(rows):
    for r in rows:
        try:
            r['likes'] = int(r.get('likes', 0))
        except (ValueError, TypeError):
            r['likes'] = 0

    rows.sort(key=lambda x: x['likes'], reverse=True)

    fieldnames = ['link', 'likes', 'status']
    with open(BACKUP_CSV, mode='w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)

def sync_backups(candidates_for_backup):
    rows = load_backup_csv()
    existing_links = {r['link'] for r in rows}

    added_count = 0
    for c in candidates_for_backup:
        likes = c.get('likesCount', 0)
        link = c.get('url') or f"https://www.instagram.com/p/{c.get('code')}/"
        
        if likes > 1000 and link and link not in existing_links:
            rows.append({
                'link': link,
                'likes': likes,
                'status': ''
            })
            added_count += 1

    save_backup_csv(rows)
    print(f"📦 Afegits {added_count} nous vídeos de backup a {BACKUP_CSV}.")

def send_telegram_summary(queue_items):
    """Envia un resum clar i intuïtiu a Telegram amb els vídeos seleccionats per avui."""
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("⚠️ TELEGRAM_TOKEN o CHAT_ID no configurats. Ometent notificació.")
        return

    print("📱 Enviant resum de la cua diària a Telegram...")
    
    header = f"<b>🚀 CUA DE VÍDEOS D'AVUI ({len(queue_items)} REELS)</b>\n\n"
    lines = []
    for item in queue_items:
        rank = item.get("rank", "")
        username = item.get("username", "desconegut")
        likes = item.get("likes", 0)
        url = item.get("url", "")
        lines.append(f"<b>#{rank}</b> | <b>@{username}</b> - ❤️ {likes:,} likes\n🔗 {url}\n")

    full_message = header + "\n".join(lines)
    url_api = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    
    chunks = [full_message[i:i+4000] for i in range(0, len(full_message), 4000)]
    for chunk in chunks:
        try:
            res = requests.post(url_api, json={
                "chat_id": CHAT_ID,
                "text": chunk,
                "disable_web_page_preview": True,
                "parse_mode": "HTML"
            }, timeout=10)
            res.raise_for_status()
        except Exception as e:
            print(f"⚠️ Error enviant missatge a Telegram: {e}")

def push_queue_and_backups():
    print("Pusheant la cua diària i backups a GitHub...")
    subprocess.run(["git", "config", "--local", "user.email", "bot@github.com"], check=True)
    subprocess.run(["git", "config", "--local", "user.name", "ViralBot"], check=True)
    
    subprocess.run(["git", "add", QUEUE_FILE], check=True)
    subprocess.run(["git", "add", BACKUP_CSV], check=True)
    
    commit_res = subprocess.run(["git", "commit", "-m", "Actualitzar cua diària (20 vídeos) i backups [skip ci]"])
    if commit_res.returncode == 0:
        subprocess.run(["git", "push"], check=True)
        print("✅ Cua diària i backups actualitzats a GitHub!")

def main():
    if not APIFY_TOKEN:
        print("Error: La variable APIFY_TOKEN no està definida.")
        return

    client = ApifyClient(APIFY_TOKEN)
    accounts = load_accounts()[:8]
    
    if not accounts:
        print("Error: No s'han trobat perfils a accounts.csv")
        return

    if os.path.exists(DB_FILE):
        with open(DB_FILE, 'r', encoding='utf-8') as f:
            processed_ids = json.load(f)
    else:
        processed_ids = []

    fa_dos_dies = datetime.now(timezone.utc) - timedelta(days=2)

    print(f"🔍 Iniciant scrapping diari de {len(accounts)} perfils...")
    run_input = {
        "directUrls": accounts,
        "resultsType": "posts",
        "resultsLimit": 9
    }

    try:
        run = client.actor("apify/instagram-api-scraper").call(run_input=run_input)
        items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
        
        candidates = []
        for i in items:
            is_video = i.get("videoUrl") or i.get("type") == "Video"
            is_new_id = i.get("id") not in processed_ids
            
            post_date_raw = i.get("timestamp") or i.get("takenAt")
            is_recent = True
            if post_date_raw:
                try:
                    if isinstance(post_date_raw, (int, float)):
                        post_date = datetime.fromtimestamp(post_date_raw, tz=timezone.utc)
                    else:
                        post_date = datetime.fromisoformat(str(post_date_raw).replace("Z", "+00:00"))
                    if post_date < fa_dos_dies:
                        is_recent = False
                except Exception:
                    pass
            
            if is_video and is_new_id and is_recent:
                candidates.append(i)

        print(f"🎯 Trobats {len(candidates)} vídeos candidats recents.")
        candidates.sort(key=lambda x: x.get("likesCount", 0), reverse=True)

        # GENERAR ESTRUCTURA CLARA A TODAY_QUEUE.JSON (TOP 20)
        today_queue = []
        for idx, c in enumerate(candidates[:20], 1):
            link = c.get('url') or f"https://www.instagram.com/p/{c.get('code')}/"
            today_queue.append({
                "rank": idx,
                "id": c.get("id"),
                "username": c.get("ownerUsername") or "desconegut",
                "likes": c.get("likesCount", 0),
                "url": link,
                "videoUrl": c.get("videoUrl")
            })
        
        candidates_for_backup = candidates[20:]

        # Desar today_queue.json
        with open(QUEUE_FILE, 'w', encoding='utf-8') as f:
            json.dump(today_queue, f, indent=2)
        print(f"📋 Guardats els {len(today_queue)} millors vídeos a {QUEUE_FILE}.")

        # Enviar resum a Telegram
        if today_queue:
            send_telegram_summary(today_queue)

        # Sincronitzar la resta amb backup_reels.csv
        if candidates_for_backup:
            sync_backups(candidates_for_backup)

        push_queue_and_backups()

    except Exception as e:
        print(f"❌ Error durant el processament del scraper: {e}")

if __name__ == "__main__":
    main()