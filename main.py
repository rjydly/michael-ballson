import os
import json
import random
import requests
import telebot
from apify_client import ApifyClient

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
ZERNIO_TOKEN = os.getenv('ZERNIO_TOKEN')
IG_ACCOUNT_ID = os.getenv('INSTAGRAM_ACCOUNT_ID')

DB_FILE = 'processed_videos.json'
ACCOUNTS_FILE = 'accounts.csv'
THUMB_PATH = 'assets/thumbnail.png' # Assegura't que el fitxer existeix al repo

def upload_to_temp_host(file_path):
    """Pujar fitxer a file.io per obtenir URL pública temporal"""
    print(f"Generant URL pública per a {file_path}...")
    with open(file_path, 'rb') as f:
        # file.io s'esborra després de la primera descàrrega. Ideal per seguretat.
        res = requests.post('https://file.io', files={'file': f})
        if res.status_code == 200:
            return res.json()['link']
    return None

def zirnio_upload_media(file_url, kind):
    """Pas 1 de Zernio: Registrar la URL i obtenir un media_id"""
    url = "https://zernio.com/api/v1/media"
    headers = {"Authorization": f"Bearer {ZERNIO_TOKEN}", "Content-Type": "application/json"}
    payload = {"url": file_url, "kind": kind}
    r = requests.post(url, headers=headers, json=payload)
    r.raise_for_status()
    return r.json()["id"]

def zirnio_create_post(video_id, thumb_id, caption):
    """Pas 2 de Zernio: Crear el post final amb els IDs obtinguts"""
    url = "https://zernio.com/api/v1/posts"
    headers = {"Authorization": f"Bearer {ZERNIO_TOKEN}", "Content-Type": "application/json"}
    payload = {
        "social_account_id": IG_ACCOUNT_ID,
        "platform": "instagram",
        "type": "video",
        "caption": caption,
        "publish_at": None, # Publicar immediatament
        "media": [{"kind": "video", "media_id": video_id}],
        "platform_options": {
            "instagram": {
                "thumbnail_media_id": thumb_id
            }
        }
    }
    r = requests.post(url, headers=headers, json=payload)
    return r.json()

def process_video(video_url):
    """Processament a 1080p compatible amb Instagram/Telegram"""
    res = requests.get(video_url)
    with open("temp.mp4", "wb") as f: f.write(res.content)
    clip = VideoFileClip("temp.mp4")
    target_h = 1080
    w, h = clip.size
    target_w = int(w * (target_h / h))
    if target_w % 2 != 0: target_w -= 1

    if hasattr(clip, "resized"): clip = clip.resized(new_size=(target_w, target_h))
    else: clip = clip.resize(new_size=(target_w, target_h))

    clip.write_videofile("out.mp4", codec="libx264", audio_codec="aac", audio=True, 
                        temp_audiofile='temp-audio.m4a', remove_temp=True, 
                        ffmpeg_params=["-pix_fmt", "yuv420p"])
    clip.close()
    return "out.mp4"

def main():
    client = ApifyClient(APIFY_TOKEN)
    bot = telebot.TeleBot(TELEGRAM_TOKEN)
    
    if not os.path.exists(ACCOUNTS_FILE): return
    with open(ACCOUNTS_FILE, mode='r') as f:
        accounts = [line.strip() for line in f if "instagram.com" in line]

    if os.path.exists(DB_FILE):
        with open(DB_FILE, 'r') as f: processed_ids = json.load(f)
    else: processed_ids = []

    video_processat = False
    for _ in range(2):
        selected_account = random.choice(accounts)
        run_input = {"directUrls": [selected_account], "resultsType": "posts", "resultsLimit": 3, "onlyPostsNewerThan": "2 days"}
        
        try:
            run = client.actor("apify/instagram-api-scraper").call(run_input=run_input)
            items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
            candidates = [i for i in items if i.get("videoUrl") and i.get("id") not in processed_ids]
            
            if candidates:
                candidates.sort(key=lambda x: x.get("likesCount", 0), reverse=True)
                best = candidates[0]
                output_file = process_video(best["videoUrl"])
                author = best.get('ownerUsername', 'Instagram')
                caption = f"🔥 Viral de @{author} #reels #viral"

                # --- 1. ENVIAR A TELEGRAM (BACKUP) ---
                with open(output_file, "rb") as v:
                    bot.send_video(CHAT_ID, v, caption=f"Enviant a Instagram...\n{caption}")

                # --- 2. PUBLICAR A INSTAGRAM (ZERNIO) ---
                print("Iniciant publicació a Zernio...")
                v_public_url = upload_to_temp_host(output_file)
                t_public_url = upload_to_temp_host(THUMB_PATH)

                if v_public_url and t_public_url:
                    v_id = zirnio_upload_media(v_public_url, "video")
                    t_id = zirnio_upload_media(t_public_url, "image")
                    result = zirnio_create_post(v_id, t_id, caption)
                    print(f"Zernio Response: {result}")
                    bot.send_message(CHAT_ID, f"✅ Publicat a Instagram: {result.get('message', 'OK')}")
                
                processed_ids.append(best["id"])
                with open(DB_FILE, 'w') as f: json.dump(processed_ids[-500:], f)
                video_processat = True
                break
        except Exception as e:
            print(f"Error: {e}")
            bot.send_message(CHAT_ID, f"❌ Error: {e}")

if __name__ == "__main__":
    main()