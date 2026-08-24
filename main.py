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

    print(f"Descarregant vídeo de @{username}...")
    res = requests.get(video_url)
    with open("temp.mp4", "wb") as f:
        f.write(res.content)

    # --- PROCESSAMENT ---
    print("Processant vídeo i àudio...")
    clip = VideoFileClip("temp.mp4")
    
    # Dimensions parelles (Fix anterior)
    target_h = 720
    w, h = clip.size
    target_w = int(w * (target_h / h))
    if target_w % 2 != 0: target_w -= 1

    # Redimensionar
    try:
        if hasattr(clip, "resized"):
            clip = clip.resized(new_size=(target_w, target_h))
        else:
            clip = clip.resize(new_size=(target_w, target_h))
    except Exception as e:
        print(f"Error redimensionant: {e}")

    # --- ESCRIPTURA DEL FITXER AMB ÀUDIO FORÇAT ---
    clip.write_videofile(
        "out.mp4", 
        codec="libx264", 
        audio_codec="aac",        # Còdec d'àudio estàndard
        audio=True,               # Forcem que hi hagi àudio
        temp_audiofile='temp-audio.m4a', # Fitxer temporal per evitar errors de buffer
        remove_temp=True,         # Esborra el temporal en acabar
        ffmpeg_params=["-pix_fmt", "yuv420p"]
    )
    clip.close()

    print("Enviant a Telegram...")
    with open("out.mp4", "rb") as v:
        bot.send_video(CHAT_ID, v, caption=f"🔥 Nou vídeo de @{username}")

    # Guardar ID
    processed_ids.append(v_id)
    with open(DB_FILE, 'w') as f:
        json.dump(processed_ids[-500:], f)

if __name__ == "__main__":
    main()