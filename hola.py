import os
import csv
import json
import random
import requests
from apify_client import ApifyClient
from moviepy.editor import VideoFileClip
import telebot

# Configuració
APIFY_TOKEN = os.getenv('APIFY_TOKEN')
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
CHAT_ID = os.getenv('CHAT_ID')
DB_FILE = 'processed_videos.json'
ACCOUNTS_FILE = 'accounts.csv'

def load_accounts():
    with open(ACCOUNTS_FILE, mode='r') as f:
        return [line.strip() for line in f if "instagram.com" in line]

def main():
    client = ApifyClient(APIFY_TOKEN)
    bot = telebot.TeleBot(TELEGRAM_TOKEN)
    
    # 1. Triar NOMÉS 1 compte aleatori per estalviar
    all_accounts = load_accounts()
    selected_account = random.choice(all_accounts)
    
    if os.path.exists(DB_FILE):
        with open(DB_FILE, 'r') as f:
            processed_ids = json.load(f)
    else:
        processed_ids = []

    # 2. Scrapejar només 3 posts d'aquest compte (mínim cost, màxima eficiència)
    run_input = {
        "directUrls": [selected_account],
        "resultsType": "posts",
        "resultsLimit": 3, 
        "onlyPostsNewerThan": "2 days" # Donem marge de 2 dies per si un dia no publica
    }

    print(f"Mirant compte: {selected_account}")
    run = client.actor("apify/instagram-api-scraper").call(run_input=run_input)
    items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
    
    # 3. Filtrar vídeos nous
    candidates = [i for i in items if i.get("videoUrl") and i.get("id") not in processed_ids]

    if not candidates:
        print("Cap vídeo nou o interessant en aquest compte ara mateix.")
        return

    # Triem el que tingui més likes d'entre els 3
    best_video = max(candidates, key=lambda x: x.get("likesCount", 0))
    
    # 4. Processament i enviament
    video_url = best_video["videoUrl"]
    print(f"Processant vídeo viral de @{best_video.get('ownerUsername')}")

    res = requests.get(video_url)
    with open("temp.mp4", "wb") as f:
        f.write(res.content)

    # MoviePy: Reduïm pes per assegurar que Telegram no doni problemes
    clip = VideoFileClip("temp.mp4")
    clip.resize(height=720).write_videofile("out.mp4", codec="libx264", audio_codec="aac")
    clip.close()

    with open("out.mp4", "rb") as v:
        bot.send_video(CHAT_ID, v, caption=f"🔥 @{best_video.get('ownerUsername')}\n❤️ {best_video.get('likesCount')} likes")

    # 5. Actualitzar DB
    processed_ids.append(best_video["id"])
    with open(DB_FILE, 'w') as f:
        json.dump(processed_ids[-500:], f)

if __name__ == "__main__":
    main()