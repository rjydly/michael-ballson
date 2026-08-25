import os
import csv
import json
import random
import requests
from apify_client import ApifyClient

# --- INTENT DE MOVIEPY ---
try:
    from moviepy.editor import VideoFileClip
except (ImportError, ModuleNotFoundError):
    try:
        from moviepy import VideoFileClip
    except ImportError:
        print("Error: No s'ha trobat MoviePy.")

# --- CONFIGURACIÓ ---
APIFY_TOKEN = os.getenv('APIFY_TOKEN')
ZERNIO_TOKEN = os.getenv('ZERNIO_TOKEN')
SOCIAL_ACCOUNT_ID = os.getenv('INSTAGRAM_ACCOUNT_ID')

DB_FILE = 'processed_videos.json'
ACCOUNTS_FILE = 'accounts.csv'
VIDEO_DIR = 'videos'
THUMB_PATH = 'assets/thumbnail.png'

# --- CAPTION (edita'l aquí) ---
CAPTION = "Hello"  # Canvia-ho pel text que vulguis

def load_accounts():
    if not os.path.exists(ACCOUNTS_FILE):
        return []
    with open(ACCOUNTS_FILE, mode='r') as f:
        return [line.strip() for line in f if "instagram.com" in line]

def process_video(video_url, output_path):
    """Descarrega, processa a 1080p i guarda a output_path."""
    print("Descarregant vídeo...")
    res = requests.get(video_url, stream=True)
    if res.status_code != 200:
        raise Exception("No s'ha pogut descarregar el vídeo")
    with open("temp.mp4", "wb") as f:
        f.write(res.content)

    print("Processant a 1080p...")
    clip = VideoFileClip("temp.mp4")
    
    target_h = 1080
    w, h = clip.size
    target_w = int(w * (target_h / h))
    if target_w % 2 != 0:
        target_w -= 1

    if hasattr(clip, "resized"):
        clip = clip.resized(new_size=(target_w, target_h))
    else:
        clip = clip.resize(new_size=(target_w, target_h))

    clip.write_videofile(
        output_path,
        codec="libx264",
        audio_codec="aac",
        audio=True,
        temp_audiofile='temp-audio.m4a',
        remove_temp=True,
        ffmpeg_params=["-pix_fmt", "yuv420p"]
    )
    clip.close()
    os.remove("temp.mp4")
    print(f"Vídeo processat i guardat a {output_path}")

def upload_to_fileio(file_path):
    """Puja un fitxer a File.io i retorna la URL pública (vàlida 24h)."""
    print(f"Pujant {file_path} a File.io...")
    with open(file_path, 'rb') as f:
        files = {'file': f}
        resp = requests.post('https://file.io', files=files, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        if not data.get('success'):
            raise Exception("File.io no ha acceptat el fitxer")
        return data['link']

def create_zernio_post(video_url, thumb_url, caption, social_account_id):
    """
    Crea un post a Zernio amb URLs públiques.
    """
    url = "https://zernio.com/api/v1/posts"
    headers = {
        "Authorization": f"Bearer {ZERNIO_TOKEN}",
        "Content-Type": "application/json"
    }
    
    # Generem scheduled_at per a 10 minuts en el futur (format ISO)
    from datetime import datetime, timedelta, timezone
    scheduled_at = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    
    payload = {
        "social_account_id": social_account_id,
        "platform": "instagram",
        "type": "video",
        "caption": caption,
        "scheduled_at": scheduled_at,
        "media": {
            "video_url": video_url,
            "thumbnail_url": thumb_url
        },
        "platform_settings": {
            "hide_likes": True
        }
    }
    
    print("Enviant a Zernio...")
    resp = requests.post(url, headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    return resp.json()

def main():
    # Comprovar tokens
    if not APIFY_TOKEN:
        print("Error: APIFY_TOKEN no definit")
        return
    if not ZERNIO_TOKEN:
        print("Error: ZERNIO_TOKEN no definit")
        return
    if not SOCIAL_ACCOUNT_ID:
        print("Error: INSTAGRAM_ACCOUNT_ID no definit")
        return

    # Crear carpetes
    os.makedirs(VIDEO_DIR, exist_ok=True)
    if not os.path.exists(THUMB_PATH):
        print(f"Error: no es troba la thumbnail a {THUMB_PATH}")
        return

    accounts = load_accounts()
    if not accounts:
        print("Error: No hi ha comptes a accounts.csv")
        return

    if os.path.exists(DB_FILE):
        with open(DB_FILE, 'r') as f:
            processed_ids = json.load(f)
    else:
        processed_ids = []

    video_publicat = False
    for _ in range(2):
        selected_account = random.choice(accounts)
        print(f"Provant compte: {selected_account}")

        try:
            client = ApifyClient(APIFY_TOKEN)
            run_input = {
                "directUrls": [selected_account],
                "resultsType": "posts",
                "resultsLimit": 3,
                "onlyPostsNewerThan": "2 days"
            }

            run = client.actor("apify/instagram-api-scraper").call(run_input=run_input)
            items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
            
            candidates = [
                i for i in items
                if (i.get("videoUrl") or i.get("type") == "Video")
                and i.get("id") not in processed_ids
            ]
            
            if not candidates:
                print(f"No hi ha res nou a {selected_account}.")
                continue

            candidates.sort(key=lambda x: x.get("likesCount", 0), reverse=True)
            best_video = candidates[0]
            video_id = best_video["id"]
            video_url = best_video["videoUrl"]
            
            # Processar vídeo
            output_filename = f"video_{video_id}.mp4"
            output_path = os.path.join(VIDEO_DIR, output_filename)
            process_video(video_url, output_path)
            
            # Pujar a File.io
            video_file_url = upload_to_fileio(output_path)
            thumb_file_url = upload_to_fileio(THUMB_PATH)
            print(f"Video URL: {video_file_url}")
            print(f"Thumb URL: {thumb_file_url}")
            
            # Publicar a Zernio
            result = create_zernio_post(
                video_url=video_file_url,
                thumb_url=thumb_file_url,
                caption=CAPTION,
                social_account_id=SOCIAL_ACCOUNT_ID
            )
            print("✅ Publicat correctament a Zernio:", result)

            # Guardar ID a l'historial
            processed_ids.append(video_id)
            with open(DB_FILE, 'w') as f:
                json.dump(processed_ids[-500:], f)
            
            # Netejar fitxers locals
            # os.remove(output_path)  # Opcional
            
            video_publicat = True
            break

        except Exception as e:
            print(f"Error amb el compte {selected_account}: {e}")
            continue

    if not video_publicat:
        print("No s'ha pogut publicar cap vídeo.")

if __name__ == "__main__":
    main()