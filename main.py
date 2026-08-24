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

def process_and_send(video_data, bot, processed_ids):
    """Funció interna per processar el vídeo i enviar-lo."""
    v_id = video_data["id"]
    video_url = video_data.get("videoUrl")
    username = video_data.get("ownerUsername", "Instagram")

    print(f"Descarregant vídeo de @{username}...")
    res = requests.get(video_url)
    with open("temp.mp4", "wb") as f:
        f.write(res.content)

    print("Processant vídeo...")
    clip = VideoFileClip("temp.mp4")
    
    # Dimensions parelles per a H.264
    target_h = 720
    w, h = clip.size
    target_w = int(w * (target_h / h))
    if target_w % 2 != 0: target_w -= 1

    try:
        if hasattr(clip, "resized"):
            clip = clip.resized(new_size=(target_w, target_h))
        else:
            clip = clip.resize(new_size=(target_w, target_h))
    except: pass

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
        bot.send_video(CHAT_ID, v, caption=f"🔥 Nou vídeo de @{username}")

    # Guardar a la base de dades
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

    # LÒGICA DE REINTENT: Provarem fins a 2 comptes diferents
    MAX_ATTEMPTS = 2
    video_trobat = False

    for attempt in range(MAX_ATTEMPTS):
        selected_account = random.choice(all_accounts)
        print(f"Intent {attempt+1}: Provant compte {selected_account}")

        # Demanem 3 posts per tenir marge (penúltims, etc.)
        run_input = {
            "directUrls": [selected_account],
            "resultsType": "posts",
            "resultsLimit": 3, 
            "onlyPostsNewerThan": "2 days" # Donem 2 dies de marge
        }

        try:
            run = client.actor("apify/instagram-api-scraper").call(run_input=run_input)
            items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
            
            # Busquem el primer vídeo de la llista que no haguem enviat
            for item in items:
                if (item.get("videoUrl") or item.get("type") == "Video") and item.get("id") not in processed_ids:
                    video_trobat = process_and_send(item, bot, processed_ids)
                    break
            
            if video_trobat:
                print("Vídeo trobat i enviat amb èxit.")
                break
            else:
                print(f"No hi ha vídeos nous al compte {selected_account}.")
        
        except Exception as e:
            print(f"Error en l'intent {attempt+1}: {e}")

    if not video_trobat:
        print("S'han esgotat els intents i no s'ha trobat cap vídeo nou a cap compte.")

if __name__ == "__main__":
    main()