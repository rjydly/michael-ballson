import os
import csv
import json
import random
import requests
from apify_client import ApifyClient
import telebot

# Solució al problema de MoviePy v1 vs v2
try:
    from moviepy.editor import VideoFileClip
except (ImportError, ModuleNotFoundError):
    from moviepy import VideoFileClip

# Configuració
APIFY_TOKEN = os.getenv('APIFY_TOKEN')
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
CHAT_ID = os.getenv('CHAT_ID')
DB_FILE = 'processed_videos.json'
ACCOUNTS_FILE = 'accounts.csv'

def load_accounts():
    if not os.path.exists(ACCOUNTS_FILE):
        return []
    with open(ACCOUNTS_FILE, mode='r') as f:
        return [line.strip() for line in f if "instagram.com" in line]

def main():
    client = ApifyClient(APIFY_TOKEN)
    bot = telebot.TeleBot(TELEGRAM_TOKEN)
    
    all_accounts = load_accounts()
    if not all_accounts:
        print("Error: No hi ha comptes al fitxer accounts.csv")
        return

    selected_account = random.choice(all_accounts)
    
    if os.path.exists(DB_FILE):
        with open(DB_FILE, 'r') as f:
            processed_ids = json.load(f)
    else:
        processed_ids = []

    print(f"Scrapejant compte: {selected_account}")

    run_input = {
        "directUrls": [selected_account],
        "resultsType": "posts",
        "resultsLimit": 1, 
        "onlyPostsNewerThan": "1 days"
    }

    # Executar Scraper
    run = client.actor("apify/instagram-api-scraper").call(run_input=run_input)
    items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
    
    # Filtrar i buscar vídeo
    candidates = [i for i in items if i.get("videoUrl") and i.get("id") not in processed_ids]

    if not candidates:
        print("No s'han trobat vídeos nous.")
        return

    video_data = candidates[0]
    video_url = video_data["videoUrl"]
    v_id = video_data["id"]

    # 1. Descarregar (Substitueix yt-dlp perquè ja tenim el link directe)
    print("Descarregant vídeo...")
    res = requests.get(video_url)
    with open("temp.mp4", "wb") as f:
        f.write(res.content)

    # 2. Processar amb MoviePy (Per compatibilitat i mida)
    print("Processant vídeo amb MoviePy...")
    clip = VideoFileClip("temp.mp4")
    # Redimensionem a 720p d'altura per estalviar espai
    clip.resize(height=720).write_videofile("out.mp4", codec="libx264", audio_codec="aac")
    clip.close()

    # 3. Enviar a Telegram
    print("Enviant a Telegram...")
    with open("out.mp4", "rb") as v:
        bot.send_video(CHAT_ID, v, caption=f"🔥 Nou vídeo de @{video_data.get('ownerUsername')}")

    # 4. Actualitzar base de dades
    processed_ids.append(v_id)
    with open(DB_FILE, 'w') as f:
        json.dump(processed_ids[-500:], f)

if __name__ == "__main__":
    main()