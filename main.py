import os
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
    
    if not os.path.exists(VIDEO_FOLDER): os.makedirs(VIDEO_FOLDER)
    else:
        for f in os.listdir(VIDEO_FOLDER):
            try: os.remove(os.path.join(VIDEO_FOLDER, f))
            except: pass

    if not os.path.exists(ACCOUNTS_FILE): return
    with open(ACCOUNTS_FILE, mode='r') as f:
        all_accounts = [line.strip() for line in f if "instagram.com" in line]

    if os.path.exists(DB_FILE):
        with open(DB_FILE, 'r') as f: processed_ids = json.load(f)
    else: processed_ids = []

    selected_account = random.choice(all_accounts)
    run_input = {"directUrls": [selected_account], "resultsType": "posts", "resultsLimit": 3, "onlyPostsNewerThan": "2 days"}
    run = client.actor("apify/instagram-api-scraper").call(run_input=run_input)
    items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
    
    video_data = next((i for i in items if i.get("videoUrl") and i.get("id") not in processed_ids), None)
    if not video_data: return

    # Processament a 1080p
    res = requests.get(video_data["videoUrl"])
    with open("temp.mp4", "wb") as f: f.write(res.content)

    clip = VideoFileClip("temp.mp4")
    target_h = 1080
    w, h = clip.size
    target_w = int(w * (target_h / h))
    if target_w % 2 != 0: target_w -= 1
    
    if hasattr(clip, "resized"): clip = clip.resized(new_size=(target_w, target_h))
    else: clip = clip.resize(new_size=(target_w, target_h))
    
    clip.write_videofile(os.path.join(VIDEO_FOLDER, "reels_upload.mp4"), 
                        codec="libx264", audio_codec="aac", audio=True,
                        ffmpeg_params=["-pix_fmt", "yuv420p"])
    clip.close()

    # Guardar dades
    processed_ids.append(video_data["id"])
    with open(DB_FILE, 'w') as f: json.dump(processed_ids[-500:], f)
    with open("current_author.txt", "w") as f: f.write(video_data.get('ownerUsername', 'Instagram'))

if __name__ == "__main__":
    main()