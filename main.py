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
        print("Error: No s'ha trobat MoviePy.")

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

def process_video(video_url):
    """Descarrega i processa el vídeo a 1080p compatible amb mòbil."""
    print("Descarregant vídeo...")
    res = requests.get(video_url)
    with open("temp.mp4", "wb") as f:
        f.write(res.content)

    print("Processant a 1080p...")
    clip = VideoFileClip("temp.mp4")
    
    # Calcular dimensions parelles per a 1080p
    target_h = 1080
    w, h = clip.size
    target_w = int(w * (target_h / h))
    if target_w % 2 != 0: target_w -= 1

    # Redimensionar segons versió de MoviePy
    if hasattr(clip, "resized"):
        clip = clip.resized(new_size=(target_w, target_h))
    else:
        clip = clip.resize(new_size=(target_w, target_h))

    # Escriptura amb còdecs de màxima compatibilitat
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
    return "out.mp4"

def main():
    client = ApifyClient(APIFY_TOKEN)
    bot = telebot.TeleBot(TELEGRAM_TOKEN)
    
    accounts = load_accounts()
    if not accounts: return

    if os.path.exists(DB_FILE):
        with open(DB_FILE, 'r') as f: processed_ids = json.load(f)
    else: processed_ids = []

    # Triem un compte i busquem virals (2 intents màxim)
    video_enviat = False
    for _ in range(2):
        selected_account = random.choice(accounts)
        print(f"Provant: {selected_account}")

        run_input = {
            "directUrls": [selected_account],
            "resultsType": "posts",
            "resultsLimit": 3, 
            "onlyPostsNewerThan": "2 days"
        }

        try:
            run = client.actor("apify/instagram-api-scraper").call(run_input=run_input)
            items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
            
            # Filtrem vídeos nous i ordenem per likes
            candidates = [i for i in items if (i.get("videoUrl") or i.get("type") == "Video") and i.get("id") not in processed_ids]
            
            if candidates:
                candidates.sort(key=lambda x: x.get("likesCount", 0), reverse=True)
                best_video = candidates[0]
                
                # Processar i enviar
                output_file = process_video(best_video["videoUrl"])
                
                with open(output_file, "rb") as v:
                    bot.send_video(
                        CHAT_ID, v, 
                        caption=f"🔥 Viral de @{best_video.get('ownerUsername')}\n❤️ {best_video.get('likesCount')} likes"
                    )
                
                # Guardar historial
                processed_ids.append(best_video["id"])
                with open(DB_FILE, 'w') as f: json.dump(processed_ids[-500:], f)
                
                video_enviat = True
                break
        except Exception as e:
            print(f"Error: {e}")

    if not video_enviat:
        print("No s'ha trobat res nou per enviar.")

if __name__ == "__main__":
    main()