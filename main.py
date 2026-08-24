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
        print("Error: MoviePy no trobat.")

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

def process_and_send(video_data, bot, processed_ids):
    """Processa amb correcció de dimensions, àudio i còdecs per a mòbil."""
    v_id = video_data["id"]
    video_url = video_data.get("videoUrl")
    username = video_data.get("ownerUsername", "Instagram")
    likes = video_data.get("likesCount", 0)

    print(f"Processant vídeo de @{username} ({likes} likes)...")
    res = requests.get(video_url)
    with open("temp.mp4", "wb") as f:
        f.write(res.content)

    clip = VideoFileClip("temp.mp4")
    
    # Fix dimensions parelles
    target_h = 720
    w, h = clip.size
    target_w = int(w * (target_h / h))
    if target_w % 2 != 0: target_w -= 1

    # Fix versió MoviePy
    try:
        if hasattr(clip, "resized"):
            clip = clip.resized(new_size=(target_w, target_h))
        else:
            clip = clip.resize(new_size=(target_w, target_h))
    except: pass

    # Escriptura amb àudio forçat i format de colors per a mòbil
    clip.write_videofile(
        "out.mp4", 
        codec="libx264", 
        audio_codec="aac",
        audio=True,
        temp_audiofile='temp-audio.m4a',
        remove_temp=True,
        ffmpeg_params=["-pix_fmt", "yuv420p"]
    )
    clip.close()

    with open("out.mp4", "rb") as v:
        bot.send_video(CHAT_ID, v, caption=f"🔥 Viral de @{username}\n❤️ {likes} likes")

    processed_ids.append(v_id)
    with open(DB_FILE, 'w') as f:
        json.dump(processed_ids[-500:], f)
    return True

def main():
    client = ApifyClient(APIFY_TOKEN)
    bot = telebot.TeleBot(TELEGRAM_TOKEN)
    
    all_accounts = load_accounts()
    if not all_accounts: return

    if os.path.exists(DB_FILE):
        with open(DB_FILE, 'r') as f:
            processed_ids = json.load(f)
    else:
        processed_ids = []

    video_enviat = False
    
    # ESTRATÈGIA D'ESTALVI:
    # Intent 1: Demanem 2 posts per triar el millor.
    # Intent 2: Si cal, demanem només 1 post d'un altre compte.
    for attempt in range(2):
        limit = 2 if attempt == 0 else 1
        selected_account = random.choice(all_accounts)
        
        print(f"Intent {attempt+1} ({limit} post/s): {selected_account}")

        run_input = {
            "directUrls": [selected_account],
            "resultsType": "posts",
            "resultsLimit": limit, 
            "onlyPostsNewerThan": "2 days"
        }

        try:
            run = client.actor("apify/instagram-api-scraper").call(run_input=run_input)
            items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
            
            # Filtrem vídeos nous
            candidates = [
                i for i in items 
                if (i.get("videoUrl") or i.get("type") == "Video") 
                and i.get("id") not in processed_ids
            ]

            if candidates:
                # Si n'hi ha més d'un, agafem el que té més likes
                candidates.sort(key=lambda x: x.get("likesCount", 0), reverse=True)
                video_enviat = process_and_send(candidates[0], bot, processed_ids)
                break
            else:
                print(f"No hi ha res nou a {selected_account}.")
        
        except Exception as e:
            print(f"Error: {e}")

    if not video_enviat:
        print("S'han esgotat els intents sense trobar contingut nou.")

if __name__ == "__main__":
    main()