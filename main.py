import os
import csv
import json
import random
import requests
from apify_client import ApifyClient
import telebot

# Intentem importar VideoFileClip de forma robusta
try:
    from moviepy.editor import VideoFileClip
except ImportError:
    try:
        from moviepy import VideoFileClip
    except ImportError:
        print("Error: No s'ha pogut importar MoviePy.")

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
        print("Error: accounts.csv buit o no trobat.")
        return

    selected_account = random.choice(all_accounts)
    print(f"Scrapejant compte: {selected_account}")

    if os.path.exists(DB_FILE):
        with open(DB_FILE, 'r') as f:
            processed_ids = json.load(f)
    else:
        processed_ids = []

    run_input = {
        "directUrls": [selected_account],
        "resultsType": "posts",
        "resultsLimit": 1, 
        "onlyPostsNewerThan": "1 days"
    }

    # Executar Scraper
    run = client.actor("apify/instagram-api-scraper").call(run_input=run_input)
    items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
    
    candidates = [i for i in items if (i.get("videoUrl") or i.get("type") == "Video") and i.get("id") not in processed_ids]

    if not candidates:
        print("No s'han trobat vídeos nous en les últimes 24h.")
        return

    video_data = candidates[0]
    # Instagram a vegades posa el vídeo a videoUrl, altres a displayUrl si és sidecar
    video_url = video_data.get("videoUrl") or video_data.get("displayUrl")
    v_id = video_data["id"]

    # 1. Descarregar
    print("Descarregant vídeo...")
    res = requests.get(video_url)
    with open("temp.mp4", "wb") as f:
        f.write(res.content)

    # 2. Processar amb MoviePy
    print("Processant vídeo amb MoviePy...")
    clip = VideoFileClip("temp.mp4")
    
    # Compatibilitat v1 vs v2 (resize vs resized)
    try:
        if hasattr(clip, "resized"):
            clip = clip.resized(height=720)
        else:
            clip = clip.resize(height=720)
    except Exception as e:
        print(f"Avís: No s'ha pogut redimensionar, s'enviarà original. Error: {e}")

    clip.write_videofile("out.mp4", codec="libx264", audio_codec="aac")
    clip.close()

    # 3. Enviar a Telegram
    print("Enviant a Telegram...")
    with open("out.mp4", "rb") as v:
        bot.send_video(CHAT_ID, v, caption=f"🔥 Nou vídeo de @{video_data.get('ownerUsername', 'Instagram')}")

    # 4. Actualitzar DB
    processed_ids.append(v_id)
    with open(DB_FILE, 'w') as f:
        json.dump(processed_ids[-500:], f)

if __name__ == "__main__":
    main()