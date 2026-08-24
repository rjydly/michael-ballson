import os
import csv
import json
import random
import requests
from apify_client import ApifyClient
import telebot

# --- IMPORTACIÓ ROBUSTA DE MOVIEPY ---
try:
    from moviepy.editor import VideoFileClip
except (ImportError, ModuleNotFoundError):
    try:
        from moviepy import VideoFileClip
    except ImportError:
        print("Error: No s'ha pogut importar MoviePy.")

# --- CONFIGURACIÓ ---
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
        return

    selected_account = random.choice(all_accounts)
    print(f"--- Compte: {selected_account} ---")

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

    run = client.actor("apify/instagram-api-scraper").call(run_input=run_input)
    items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
    
    video_data = None
    for i in items:
        if (i.get("videoUrl") or i.get("type") == "Video") and i.get("id") not in processed_ids:
            video_data = i
            break

    if not video_data:
        print("Cap vídeo nou.")
        return

    v_id = video_data["id"]
    video_url = video_data.get("videoUrl")
    username = video_data.get("ownerUsername", "Instagram")

    print(f"Descarregant @{username}...")
    res = requests.get(video_url)
    with open("temp.mp4", "wb") as f:
        f.write(res.content)

    # --- PROCESSAMENT AMB CORRECCIÓ DE DIMENSIONS ---
    print("Processant vídeo...")
    clip = VideoFileClip("temp.mp4")
    
    # Calculem les noves dimensions assegurant que siguin PARELLES (divisibles per 2)
    target_h = 720
    w, h = clip.size
    target_w = int(w * (target_h / h))
    
    if target_w % 2 != 0:
        target_w -= 1  # Si és senar (com 405), el convertim en parell (404)

    # Redimensionar segons versió de MoviePy
    try:
        if hasattr(clip, "resized"):
            clip = clip.resized(new_size=(target_w, target_h)) # v2.x
        else:
            clip = clip.resize(new_size=(target_w, target_h))  # v1.x
    except Exception as e:
        print(f"Error redimensionant: {e}")

    # Escriptura amb paràmetres de compatibilitat mòbil
    clip.write_videofile(
        "out.mp4", 
        codec="libx264", 
        audio_codec="aac",
        ffmpeg_params=["-pix_fmt", "yuv420p"]
    )
    clip.close()

    print("Enviant a Telegram...")
    with open("out.mp4", "rb") as v:
        bot.send_video(CHAT_ID, v, caption=f"🔥 Nou vídeo de @{username}")

    processed_ids.append(v_id)
    with open(DB_FILE, 'w') as f:
        json.dump(processed_ids[-500:], f)

if __name__ == "__main__":
    main()