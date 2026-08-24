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
    try:
        requests.post(url, json={"chat_id": CHAT_ID, "text": message})
    except:
        pass

def upload_media(url, kind, filename):
    """Pas 1: Registrar el media a Zernio enviant la URL i el filename"""
    print(f"Registrant {kind} a Zernio ({filename})...")
    headers = {
        "Authorization": f"Bearer {ZERNIO_TOKEN}",
        "Content-Type": "application/json"
    }
    # AFEGIM EL CAMP 'filename' QUE DEMANA L'ERROR
    payload = {
        "url": url, 
        "kind": kind,
        "filename": filename
    }
    
    r = requests.post(f"{BASE}/media", headers=headers, json=payload)
    
    if r.status_code not in [200, 201]:
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
    headers = {
        "Authorization": f"Bearer {ZERNIO_TOKEN}",
        "Content-Type": "application/json"
    }

    try:
        # 1. Obtenir IDs de Media (Amb el filename inclòs)
        video_id = upload_media(VIDEO_URL, "video", "reels_upload.mp4")
        thumb_id = upload_media(THUMB_URL, "image", "thumbnail.png")

        # 2. Crear el post segons la teva documentació
        payload = {
            "social_account_id": SA_ID,
            "platform": "instagram",
            "type": "video",
            "caption": caption,
            "publish_at": None, # Publicar ara mateix
            "media": [
                {
                    "kind": "video",
                    "media_id": video_id
                }
            ],
            "platform_options": {
                "instagram": {
                    "thumbnail_media_id": thumb_id
                }
            }
        }
        
        print("Creant post a Instagram...")
        post_res = requests.post(f"{BASE}/posts", headers=headers, json=payload)
        
        if post_res.status_code not in [200, 201]:
            error_msg = f"❌ Error Zernio Post: {post_res.status_code} - {post_res.text}"
            print(error_msg)
            notify_telegram(error_msg)
            return

        print(f"Èxit: {post_res.json()}")
        notify_telegram(f"✅ Publicat a Instagram: @{author}")

    except Exception as e:
        print(f"Error general: {e}")

if __name__ == "__main__":
    main()