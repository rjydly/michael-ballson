import os
import csv
import json
import random
import requests
import time
from apify_client import ApifyClient

# Intentem importar MoviePy
try:
    from moviepy.editor import VideoFileClip
except (ImportError, ModuleNotFoundError):
    from moviepy import VideoFileClip

# --- CONFIGURACIÓ ---
APIFY_TOKEN = os.getenv('APIFY_TOKEN')
ZERNIO_TOKEN = os.getenv('ZERNIO_TOKEN')
INSTAGRAM_ID = os.getenv('INSTAGRAM_ACCOUNT_ID')
DB_FILE = 'processed_videos.json'
ACCOUNTS_FILE = 'accounts.csv'
THUMBNAIL_PATH = 'assets/thumbnail.png'

def upload_to_temporary_host(file_path):
    """Puja el fitxer a file.io per obtenir una URL pública temporal (dura 1 descàrrega/1 dia)"""
    print(f"Pujant {file_path} a allotjament temporal...")
    with open(file_path, 'rb') as f:
        # file.io és gratuït i no necessita registre per a ús esporàdic
        response = requests.post('https://file.io', files={'file': f})
        if response.status_code == 200:
            return response.json()['link']
    return None

def post_to_zirnio(video_url, cover_url, caption):
    """Envia l'ordre de publicació a l'API de Zirnio"""
    url = "https://api.zirnio.com/v1/posts" # Revisa si la URL de l'API ha canviat a la seva doc
    headers = {
        "Authorization": f"Bearer {ZERNIO_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "instagram_account_id": INSTAGRAM_ID,
        "media_type": "REELS",
        "video_url": video_url,
        "cover_url": cover_url,
        "caption": caption
    }
    
    response = requests.post(url, json=payload, headers=headers)
    return response.json()

def main():
    client = ApifyClient(APIFY_TOKEN)
    
    if not os.path.exists(ACCOUNTS_FILE): return
    with open(ACCOUNTS_FILE, mode='r') as f:
        all_accounts = [line.strip() for line in f if "instagram.com" in line]

    if os.path.exists(DB_FILE):
        with open(DB_FILE, 'r') as f:
            processed_ids = json.load(f)
    else:
        processed_ids = []

    selected_account = random.choice(all_accounts)
    print(f"Buscant contingut a: {selected_account}")

    run_input = {"directUrls": [selected_account], "resultsType": "posts", "resultsLimit": 2, "onlyPostsNewerThan": "2 days"}
    run = client.actor("apify/instagram-api-scraper").call(run_input=run_input)
    items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
    
    video_data = next((i for i in items if i.get("videoUrl") and i.get("id") not in processed_ids), None)

    if not video_data:
        print("Res de nou per publicar.")
        return

    # Processament de vídeo (el mateix que teníem)
    res = requests.get(video_data["videoUrl"])
    with open("temp.mp4", "wb") as f: f.write(res.content)

    clip = VideoFileClip("temp.mp4")
    target_h = 720
    w, h = clip.size
    target_w = int(w * (target_h / h))
    if target_w % 2 != 0: target_w -= 1
    
    clip = clip.resized(new_size=(target_w, target_h)) if hasattr(clip, "resized") else clip.resize(new_size=(target_w, target_h))
    clip.write_videofile("out.mp4", codec="libx264", audio_codec="aac", ffmpeg_params=["-pix_fmt", "yuv420p"])
    clip.close()

    # --- PUBLICACIÓ A INSTAGRAM ---
    
    # 1. Obtenir URLs públiques temporals
    public_video_url = upload_to_temporary_host("out.mp4")
    public_thumb_url = upload_to_temporary_host(THUMBNAIL_PATH)

    if public_video_url and public_thumb_url:
        caption = f"🔥 Crédits: @{video_data.get('ownerUsername')} #reels #viral"
        print("Enviant a Zirnio...")
        result = post_to_zirnio(public_video_url, public_thumb_url, caption)
        print(f"Resultat Zirnio: {result}")
        
        # Guardar ID a la DB
        processed_ids.append(video_data["id"])
        with open(DB_FILE, 'w') as f: json.dump(processed_ids[-500:], f)
    else:
        print("Error en pujar els fitxers al servidor temporal.")

if __name__ == "__main__":
    main()
