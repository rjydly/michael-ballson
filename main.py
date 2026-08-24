import os
import requests
import time

BASE = "https://zernio.com/api/v1"
API_KEY = os.getenv('ZERNIO_TOKEN')
SA_ID = os.getenv('INSTAGRAM_ACCOUNT_ID')
REPO = os.getenv('GITHUB_REPOSITORY')

# URLs de GitHub
VIDEO_URL = f"https://raw.githubusercontent.com/{REPO}/main/videos/reels_upload.mp4"
THUMB_URL = f"https://raw.githubusercontent.com/{REPO}/main/assets/thumbnail.png"

headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

def upload_media(url, kind):
    print(f"Pujant {kind} a Zernio...")
    r = requests.post(f"{BASE}/media", headers=headers, json={"url": url, "kind": kind})
    r.raise_for_status()
    return r.json()["id"]

def main():
    if not os.path.exists("current_author.txt"): return
    with open("current_author.txt", "r") as f: author = f.read()

    # Pas 1: Pujar URLs a Zernio per obtenir IDs
    try:
        video_id = upload_media(VIDEO_URL, "video")
        thumb_id = upload_media(THUMB_URL, "image")
    except Exception as e:
        print(f"Error en l'upload: {e}")
        return

    # Pas 2: Crear el post final
    payload = {
        "social_account_id": SA_ID,
        "platform": "instagram",
        "type": "video",
        "caption": f"🔥 Crèdits: @{author} #reels #viral",
        "publish_at": None,  # Publicar ara
        "media": [{"kind": "video", "media_id": video_id}],
        "platform_options": {
            "instagram": {
                "thumbnail_media_id": thumb_id
            }
        }
    }

    print("Creant post a Instagram...")
    r = requests.post(f"{BASE}/posts", headers=headers, json=payload)
    print(r.json())

if __name__ == "__main__":
    main()