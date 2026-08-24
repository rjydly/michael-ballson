import os
import json
import random
import requests
import sys
from apify_client import ApifyClient

try:
    from moviepy.editor import VideoFileClip
except (ImportError, ModuleNotFoundError):
    from moviepy import VideoFileClip

# --- CONFIGURACIÓ ---
APIFY_TOKEN = os.getenv('APIFY_TOKEN')
ZERNIO_TOKEN = os.getenv('ZERNIO_TOKEN')
INSTAGRAM_ID = os.getenv('INSTAGRAM_ACCOUNT_ID')
REPO_NAME = os.getenv('GITHUB_REPOSITORY') # Format: usuari/nom-repo
DB_FILE = 'processed_videos.json'
ACCOUNTS_FILE = 'accounts.csv'
THUMBNAIL_URL = f"https://raw.githubusercontent.com/{REPO_NAME}/main/assets/thumbnail.png"
VIDEO_OUT_PATH = 'videos/out.mp4'
# URL pública on estarà el vídeo un cop fet el "push"
PUBLIC_VIDEO_URL = f"https://raw.githubusercontent.com/{REPO_NAME}/main/{VIDEO_OUT_PATH}"

def post_to_zirnio(video_url, caption):
    """Envia l'ordre de publicació a Zirnio"""
    print(f"Sol·licitant publicació a Instagram via Zirnio...")
    url = "https://api.zirnio.com/v1/posts"
    headers = {"Authorization": f"Bearer {ZERNIO_TOKEN}", "Content-Type": "application/json"}
    payload = {
        "instagram_account_id": INSTAGRAM_ID,
        "media_type": "REELS",
        "video_url": video_url,
        "cover_url": THUMBNAIL_URL,
        "caption": caption
    }
    res = requests.post(url, json=payload, headers=headers)
    return res.json()

def main():
    # Detectem si estem en fase de "PROCESSAR" o fase de "PUBLICAR"
    phase = sys.argv[1] if len(sys.argv) > 1 else "process"

    if phase == "process":
        client = ApifyClient(APIFY_TOKEN)
        with open(ACCOUNTS_FILE, mode='r') as f:
            all_accounts = [line.strip() for line in f if "instagram.com" in line]
        
        if os.path.exists(DB_FILE):
            with open(DB_FILE, 'r') as f: processed_ids = json.load(f)
        else: processed_ids = []

        selected_account = random.choice(all_accounts)
        run_input = {"directUrls": [selected_account], "resultsType": "posts", "resultsLimit": 2, "onlyPostsNewerThan": "2 days"}
        run = client.actor("apify/instagram-api-scraper").call(run_input=run_input)
        items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
        
        video_data = next((i for i in items if i.get("videoUrl") and i.get("id") not in processed_ids), None)
        if not video_data:
            print("Cap vídeo nou trobat.")
            exit(1) # Sortim amb error perquè el workflow s'aturi aquí

        # Processament
        res = requests.get(video_data["videoUrl"])
        with open("temp.mp4", "wb") as f: f.write(res.content)
        
        clip = VideoFileClip("temp.mp4")
        target_h = 720
        w, h = clip.size
        target_w = int(w * (target_h / h))
        if target_w % 2 != 0: target_w -= 1
        clip = clip.resized(new_size=(target_w, target_h)) if hasattr(clip, "resized") else clip.resize(new_size=(target_w, target_h))
        clip.write_videofile(VIDEO_OUT_PATH, codec="libx264", audio_codec="aac", ffmpeg_params=["-pix_fmt", "yuv420p"])
        clip.close()

        # Guardar ID a la DB per a la següent fase
        processed_ids.append(video_data["id"])
        video_data['username_original'] = video_data.get('ownerUsername')
        with open(DB_FILE, 'w') as f: json.dump(processed_ids, f)
        # Guardem temporalment la caption per a la fase 2
        with open("caption_temp.txt", "w") as f: 
            f.write(f"🔥 Crédits: @{video_data['username_original']} #reels #viral")

    elif phase == "publish":
        with open("caption_temp.txt", "r") as f: caption = f.read()
        print(f"Publicant vídeo des de: {PUBLIC_VIDEO_URL}")
        result = post_to_zirnio(PUBLIC_VIDEO_URL, caption)
        print(result)

if __name__ == "__main__":
    main()
