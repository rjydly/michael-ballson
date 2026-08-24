import os
import requests
import json

# --- CONFIGURACIÓ ---
ZERNIO_TOKEN = os.getenv('ZERNIO_TOKEN')
SA_ID = os.getenv('INSTAGRAM_ACCOUNT_ID')
REPO = os.getenv('GITHUB_REPOSITORY')
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
CHAT_ID = os.getenv('CHAT_ID')

BASE = "https://zernio.com/api/v1"
VIDEO_URL = f"https://raw.githubusercontent.com/{REPO}/main/videos/reels_upload.mp4"
THUMB_URL = f"https://raw.githubusercontent.com/{REPO}/main/assets/thumbnail.png"

def notify_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": CHAT_ID, "text": message})

def upload_media(url, kind):
    print(f"Registrant {kind} a Zernio...")
    headers = {"Authorization": f"Bearer {ZERNIO_TOKEN}", "Content-Type": "application/json"}
    payload = {"url": url, "kind": kind}
    
    r = requests.post(f"{BASE}/media", headers=headers, json=payload)
    
    # Si la resposta no és bona, imprimim tot el que diu l'API
    if r.status_code != 200 and r.status_code != 201:
        error_msg = f"❌ Error Zernio Media ({kind}): {r.status_code} - {r.text}"
        print(error_msg)
        notify_telegram(error_msg)
        raise Exception(error_msg)
    
    return r.json()["id"]

def main():
    if not os.path.exists("current_author.txt"): 
        print("Error: No s'ha trobat current_author.txt")
        return
        
    with open("current_author.txt", "r") as f: 
        author = f.read()
    
    caption = f"🔥 Crèdits: @{author} #reels #viral"
    headers = {"Authorization": f"Bearer {ZERNIO_TOKEN}", "Content-Type": "application/json"}

    try:
        # Pas 1: Registrar Media
        video_id = upload_media(VIDEO_URL, "video")
        thumb_id = upload_media(THUMB_URL, "image")

        # Pas 2: Crear el post
        payload = {
            "social_account_id": SA_ID,
            "platform": "instagram",
            "type": "video",
            "caption": caption,
            "media": [{"kind": "video", "media_id": video_id}],
            "platform_options": {"instagram": {"thumbnail_media_id": thumb_id}}
        }
        
        print("Creant post a Instagram...")
        post_res = requests.post(f"{BASE}/posts", headers=headers, json=payload)
        
        if post_res.status_code != 200 and post_res.status_code != 201:
            error_msg = f"❌ Error Zernio Post: {post_res.status_code} - {post_res.text}"
            print(error_msg)
            notify_telegram(error_msg)
            return

        print(f"Èxit: {post_res.json()}")
        notify_telegram(f"✅ Vídeo de @{author} publicat a Instagram correctament!")

    except Exception as e:
        print(f"Error general: {e}")

if __name__ == "__main__":
    main()