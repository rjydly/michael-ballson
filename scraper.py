import os
import csv
import json
import time
import subprocess
from datetime import datetime, timezone, timedelta
from apify_client import ApifyClient

# --- CONFIGURACIÓ ---
APIFY_TOKEN = os.getenv('APIFY_TOKEN')
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
    """Guarda el CSV ordenant sempre de MÉS VIRAL a MENYS VIRAL per likes."""
    for r in rows:
        try:
            r['likes'] = int(r.get('likes', 0))
        except (ValueError, TypeError):
            r['likes'] = 0

    # Ordenar de més a menys likes
    rows.sort(key=lambda x: x['likes'], reverse=True)

    fieldnames = ['link', 'likes', 'status']
    with open(BACKUP_CSV, mode='w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)

def sync_backups(candidates_for_backup):
    """Afegeix els candidats amb > 1000 likes al CSV de backup."""
    rows = load_backup_csv()
    existing_links = {r['link'] for r in rows}

    added_count = 0
    for c in candidates_for_backup:
        likes = c.get('likesCount', 0)
        link = c.get('url') or f"https://www.instagram.com/p/{c.get('code')}/"
        
        # Filtre: Més de 1000 likes i no existent al CSV
        if likes > 1000 and link and link not in existing_links:
            rows.append({
                'link': link,
                'likes': likes,
                'status': ''  # Pendent (camp buit)
            })
            added_count += 1

    save_backup_csv(rows)
    print(f"📦 Afegits {added_count} nous vídeos de backup a {BACKUP_CSV}.")

def push_queue_and_backups():
    print("Pusheant la cua diària i backups a GitHub...")
    subprocess.run(["git", "config", "--local", "user.email", "bot@github.com"], check=True)
    subprocess.run(["git", "config", "--local", "user.name", "ViralBot"], check=True)
    
    subprocess.run(["git", "add", QUEUE_FILE], check=True)
    subprocess.run(["git", "add", BACKUP_CSV], check=True)
    
    commit_res = subprocess.run(["git", "commit", "-m", "Actualitzar cua diària i backups [skip ci]"])
    if commit_res.returncode == 0:
        subprocess.run(["git", "push"], check=True)
        print("✅ Cua diària i backups actualitzats a GitHub!")

def main():
    if not APIFY_TOKEN:
        print("Error: La variable APIFY_TOKEN no està definida.")
        return

    client = ApifyClient(APIFY_TOKEN)
    accounts = load_accounts()[:8]  # OPCIÓ 3: Primers 8 perfils de accounts.csv
    
    if not accounts:
        print("Error: No s'han trobat perfils a accounts.csv")
        return

    if os.path.exists(DB_FILE):
        with open(DB_FILE, 'r', encoding='utf-8') as f:
            processed_ids = json.load(f)
    else:
        processed_ids = []

    fa_dos_dies = datetime.now(timezone.utc) - timedelta(days=2)

    print(f"🔍 Iniciant scrapping diari de {len(accounts)} perfils (9 posts per perfil)...")
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

        # Ordenar de més a menys likes
        candidates.sort(key=lambda x: x.get("likesCount", 0), reverse=True)

        # Els 12 primers a la cua del dia (today_queue.json)
        today_queue = candidates[:12]
        
        # La resta (a partir del 13è) al backup si tenen > 1000 likes
        candidates_for_backup = candidates[12:]

        # Desar today_queue.json
        with open(QUEUE_FILE, 'w', encoding='utf-8') as f:
            json.dump(today_queue, f, indent=2)
        print(f"📋 Guardats els {len(today_queue)} millors vídeos a {QUEUE_FILE}.")

        # Sincronitzar la resta amb backup_reels.csv
        if candidates_for_backup:
            sync_backups(candidates_for_backup)

        push_queue_and_backups()

    except Exception as e:
        print(f"❌ Error durant el processament del scraper: {e}")

if __name__ == "__main__":
    main()