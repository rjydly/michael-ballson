import os
import requests
import time

# --- CONFIGURACIÓ ---
ZERNIO_TOKEN = os.getenv('ZERNIO_TOKEN')
SA_ID = os.getenv('INSTAGRAM_ACCOUNT_ID')
REPO = os.getenv('GITHUB_REPOSITORY')
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
CHAT_ID = os.getenv('CHAT_ID')

BASE = "https://zernio.com/api/v1"
VIDEO_URL = f"https://raw.githubusercontent.com/{REPO}/main/videos/reels_upload.mp4"
THUMB_URL = f"https://raw.githubusercontent.com/{REPO}/main/assets/thumbnail.png"

def main():
    if not os.path.exists("current_author.txt"): return
    with open("current_author.txt", "r") as f: author = f.read()
    caption = f"🔥 Crèdits: @{author} #reels #viral"

    headers = {"Authorization": f"Bearer {ZERNIO_TOKEN}", "Content-Type": "application/json"}

    try:
        # 1. Registrar Media a Zernio
        print("Registrant vídeo a Zernio...")
        v_res = requests.post(f"{BASE}/media", headers=headers, json={"url": VIDEO_URL, "kind": "video"})
        v_id = v_res.json()["id"]

        print("Registrant miniatura a Zernio...")
        t_res = requests.post(f"{BASE}/media", headers=headers, json={"url": THUMB_URL, "kind": "image"})
        t_id = t_res.json()["id"]

        # 2. Publicar Post
        payload = {
            "social_account_id": SA_ID,
            "platform": "instagram",
            "type": "video",
            "caption": caption,
            "media": [{"kind": "video", "media_id": v_id}],
            "platform_options": {"instagram": {"thumbnail_media_id": t_id}}
        }
        print("Creant post a Instagram...")
        post_res = requests.post(f"{BASE}/posts", headers=headers, json=payload)
        print(f"Zernio: {post_res.json().get('message', 'OK')}")

        # 3. Notificar a Telegram (URL de confirmació)
        # Fem servir un link simple per evitar el timeout de pujada de fitxer
        msg = f"✅ Vídeo de @{author} enviat a Instagram!\n\nPots veure'l aquí:\n{VIDEO_URL}"
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", 
                      json={"chat_id": CHAT_ID, "text": msg})

    except Exception as e:
        print(f"Error: {e}")
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", 
                      json={"chat_id": CHAT_ID, "text": f"❌ Error publicant: {e}"})

if __name__ == "__main__":
    main()