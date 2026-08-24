import os
import csv
import json
import random
import requests
from apify_client import ApifyClient

try:
    from moviepy.editor import VideoFileClip
except (ImportError, ModuleNotFoundError):
    from moviepy import VideoFileClip

# --- CONFIGURACIÓ ---
APIFY_TOKEN = os.getenv('APIFY_TOKEN')
DB_FILE = 'processed_videos.json'
ACCOUNTS_FILE = 'accounts.csv'
VIDEO_FOLDER = 'videos'

def main():
    client = ApifyClient(APIFY_TOKEN)
    
    # 1. Netejar carpeta "videos" (esborra tot el contingut anterior)
    if not os.path.exists(VIDEO_FOLDER):
        os.makedirs(VIDEO_FOLDER)
    else:
        print("Netejant vídeos anteriors...")
        for f in os.listdir(VIDEO_FOLDER):
            file_path = os.path.join(VIDEO_FOLDER, f)
            try:
                if os.path.isfile(file_path): os.remove(file_path)
            except Exception as e: print(f"Error esborrant {f}: {e}")

    if not os.path.exists(ACCOUNTS_FILE):
        print("Error: No s'ha trobat accounts.csv")
        return

    with open(ACCOUNTS_FILE, mode='r') as f:
        all_accounts = [line.strip() for line in f if "instagram.com" in line]

    if os.path.exists(DB_FILE):
        with open(DB_FILE, 'r') as f:
            processed_ids = json.load(f)
    else:
        processed_ids = []

    selected_account = random.choice(all_accounts)
    print(f"Scrapejant: {selected_account}")

    run_input = {
        "directUrls": [selected_account], 
        "resultsType": "posts", 
        "resultsLimit": 2, 
        "onlyPostsNewerThan": "2 days"
    }
    
    run = client.actor("apify/instagram-api-scraper").call(run_input=run_input)
    items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
    
    # Busquem un vídeo que no haguem processat
    video_data = next((i for i in items if (i.get("videoUrl") or i.get("type") == "Video") and i.get("id") not in processed_ids), None)

    if not video_data:
        print("Cap vídeo nou trobat.")
        return

    # Processament MoviePy
    print(f"Descarregant vídeo de @{video_data.get('ownerUsername')}...")
    res = requests.get(video_data["videoUrl"])
    with open("temp.mp4", "wb") as f: f.write(res.content)

    clip = VideoFileClip("temp.mp4")
    target_h = 720
    w, h = clip.size
    target_w = int(w * (target_h / h))
    if target_w % 2 != 0: target_w -= 1
    
    if hasattr(clip, "resized"):
        clip = clip.resized(new_size=(target_w, target_h))
    else:
        clip = clip.resize(new_size=(target_w, target_h))
    
    # Guardem al repositori
    video_path = os.path.join(VIDEO_FOLDER, "reels_upload.mp4")
    clip.write_videofile(video_path, codec="libx264", audio_codec="aac", ffmpeg_params=["-pix_fmt", "yuv420p"])
    clip.close()

    # Guardar ID i autor per al següent pas
    processed_ids.append(video_data["id"])
    with open(DB_FILE, 'w') as f: json.dump(processed_ids[-500:], f)
    
    with open("current_author.txt", "w") as f:
        f.write(video_data.get('ownerUsername', 'Instagram'))
    
    print("Vídeo llest per ser pujat al repositori.")

if __name__ == "__main__":
    main()