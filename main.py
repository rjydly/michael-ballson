import os
import csv
import json
import time
import random
import requests
import subprocess
import yt_dlp
from datetime import datetime, timezone, timedelta
from apify_client import ApifyClient

# --- IMPORTACIÓ ROBUSTA DE MOVIEPY ---
try:
    from moviepy.editor import VideoFileClip, ImageClip, concatenate_videoclips
except (ImportError, ModuleNotFoundError):
    try:
        from moviepy import VideoFileClip, ImageClip, concatenate_videoclips
    except ImportError:
        print("Error: No s'ha trobat MoviePy.")

# --- CONFIGURACIÓ ---
APIFY_TOKEN = os.getenv('APIFY_TOKEN')
BUFFER_ACCESS_TOKEN = os.getenv('BUFFER_ACCESS_TOKEN')
BUFFER_CHANNEL_ID = os.getenv('BUFFER_CHANNEL_ID')
GITHUB_REPOSITORY = os.getenv('GITHUB_REPOSITORY')

DEFAULT_CAPTION = "Tonight, V stepped into the crowd, taking in live performances at Vogue World: Hollywood. Known for his own standout fashion moments, he kept it effortlessly stylish in a look worthy of the runway."

DB_FILE = 'processed_videos.json'
ACCOUNTS_FILE = 'accounts.csv'
BACKUP_CSV = 'backup_reels.csv'
VIDEOS_DIR = 'videos'

def load_accounts():
    if not os.path.exists(ACCOUNTS_FILE):
        return []
    with open(ACCOUNTS_FILE, mode='r') as f:
        return [line.strip() for line in f if "instagram.com" in line]

def clean_videos_folder():
    """Neteja la carpeta videos/ eliminant qualsevol fitxer anterior."""
    if not os.path.exists(VIDEOS_DIR):
        os.makedirs(VIDEOS_DIR)
        print(f"Carpeta {VIDEOS_DIR} creada.")
    else:
        print(f"Netejant la carpeta {VIDEOS_DIR}...")
        for filename in os.listdir(VIDEOS_DIR):
            file_path = os.path.join(VIDEOS_DIR, filename)
            if os.path.isfile(file_path):
                os.remove(file_path)
        print("Carpeta netejada correctament.")

# --- GESTIÓ DEL CSV DE BACKUP (link, likes, status) ---

def load_backup_csv():
    """Carrega el CSV de backup."""
    if not os.path.exists(BACKUP_CSV):
        return []
    rows = []
    with open(BACKUP_CSV, mode='r', newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows

def save_backup_csv(rows):
    """Guarda el CSV ordenant sempre de MÉS VIRAL a MENYS VIRAL per likes."""
    for r in rows:
        try:
            r['likes'] = int(r.get('likes', 0))
        except (ValueError, TypeError):
            r['likes'] = 0

    # Ordenar de més a menys likes
    rows.sort(key=lambda x: x['likes'], reverse=True)

    fieldnames = ['link', 'likes', 'status']
    with open(BACKUP_CSV, mode='w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)

def sync_candidates_to_backup_csv(candidates):
    """Afegeix els candidats nous trobats per Apify al CSV de backup."""
    rows = load_backup_csv()
    existing_links = {r['link'] for r in rows}

    for c in candidates:
        link = c.get('url') or f"https://www.instagram.com/p/{c.get('code')}/"
        if link and link not in existing_links:
            likes = c.get('likesCount', 0)
            rows.append({
                'link': link,
                'likes': likes,
                'status': '' # Pendent
            })

    save_backup_csv(rows)

def mark_link_status_in_csv(link, status):
    """Actualitza l'estat d'un link al CSV ('done' o 'failed')."""
    rows = load_backup_csv()
    for r in rows:
        if r['link'] == link:
            r['status'] = status
            break
    save_backup_csv(rows)

# --- DESCÀRREGA I PROCESSAMENT DE VÍDEOS ---

def download_video_file(url, target_path):
    """Descarrega directament des de la URL de CDN d'Apify."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "*/*"
    }
    for attempt in range(1, 4):
        try:
            print(f"Intent {attempt}/3 de descàrrega des de CDN...")
            res = requests.get(url, headers=headers, timeout=30, stream=True)
            res.raise_for_status()
            with open(target_path, "wb") as f:
                for chunk in res.iter_content(chunk_size=8192):
                    f.write(chunk)
            print("Descàrrega completada amb èxit.")
            return True
        except Exception as e:
            print(f"⚠️ Error a l'intent {attempt}: {e}")
            time.sleep(3)
    return False

def download_reel_with_ytdlp(reel_url, target_path="temp.mp4"):
    """Descarrega un Reel d'Instagram fent servir yt-dlp."""
    print(f"Descarregant Reel amb yt-dlp: {reel_url}")
    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': target_path,
        'quiet': True,
        'overwrites': True
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([reel_url])
    return target_path

def process_downloaded_video(local_file_path):
    """Processa el fitxer de vídeo descarregat a 1080p, afegeix la thumbnail al frame 0 i el guarda a videos/out.mp4."""
    print("Processant vídeo a 1080p i afegint la portada al primer frame...")
    clip = VideoFileClip(local_file_path)
    
    target_h = 1080
    w, h = clip.size
    target_w = int(w * (target_h / h))
    if target_w % 2 != 0: target_w -= 1

    if hasattr(clip, "resized"):
        clip = clip.resized(new_size=(target_w, target_h))
    else:
        clip = clip.resize(new_size=(target_w, target_h))

    thumb_path = os.path.join("assets", "thumbnail.png")
    if os.path.exists(thumb_path):
        img = ImageClip(thumb_path)
        thumb_clip = img.with_duration(0.1) if hasattr(img, "with_duration") else img.set_duration(0.1)
        thumb_clip = thumb_clip.resized(new_size=(target_w, target_h)) if hasattr(thumb_clip, "resized") else thumb_clip.resize(new_size=(target_w, target_h))
        final_clip = concatenate_videoclips([thumb_clip, clip])
    else:
        print("⚠️ Avís: No s'ha trobat assets/thumbnail.png. Es processarà sense portada.")
        final_clip = clip

    output_path = os.path.join(VIDEOS_DIR, "out.mp4")
    
    final_clip.write_videofile(
        output_path, 
        codec="libx264", 
        audio_codec="aac",
        audio=True,
        bitrate="3500k",
        temp_audiofile='temp-audio.m4a',
        remove_temp=True,
        ffmpeg_params=["-pix_fmt", "yuv420p", "-crf", "24"]
    )
    clip.close()
    if os.path.exists(thumb_path):
        final_clip.close()
    if os.path.exists(local_file_path):
        os.remove(local_file_path)

    file_size_mb = os.path.getsize(output_path) / (1024 * 1024)
    print(f"📦 Mida final del vídeo: {file_size_mb:.2f} MB")
    if file_size_mb > 48:
        raise Exception(f"El vídeo generat pesa massa ({file_size_mb:.2f} MB) i supera el límit de GitHub.")

    return output_path

# --- OPERACIONS DE GITHUB I BUFFER ---

def push_to_github_and_get_raw_url(filepath):
    """Pushea el vídeo i els fitxers de registre a GitHub."""
    print("Pusheant el nou vídeo i registres a GitHub...")
    
    subprocess.run(["git", "config", "--local", "user.email", "bot@github.com"], check=True)
    subprocess.run(["git", "config", "--local", "user.name", "ViralBot"], check=True)
    
    subprocess.run(["git", "add", "-f", filepath], check=True)
    subprocess.run(["git", "add", DB_FILE], check=True)
    subprocess.run(["git", "add", BACKUP_CSV], check=True)
    
    commit_res = subprocess.run(["git", "commit", "-m", "Actualitzar vídeo i backups [skip ci]"])
    if commit_res.returncode == 0:
        subprocess.run(["git", "push"], check=True)
        print("Esperant 5 segons per a la propagació de GitHub Raw...")
        time.sleep(5)
    
    filename = os.path.basename(filepath)
    raw_url = f"https://raw.githubusercontent.com/{GITHUB_REPOSITORY}/main/videos/{filename}"
    print(f"🔗 URL pública de GitHub generada: {raw_url}")
    return raw_url

def publish_to_buffer(video_public_url, caption):
    """Publica el vídeo directament a Instagram via Buffer."""
    print("Publicant directament a Instagram via Buffer...")
    
    query = """
    mutation CreatePost($input: CreatePostInput!) {
      createPost(input: $input) {
        ... on PostActionSuccess {
          post {
            id
          }
        }
        ... on MutationError {
          message
        }
      }
    }
    """

    variables = {
        "input": {
            "text": caption,
            "channelId": BUFFER_CHANNEL_ID,
            "schedulingType": "automatic",
            "mode": "shareNow",
            "assets": [
                {
                    "video": {
                        "url": video_public_url,
                        "metadata": {
                            "thumbnailOffset": 0
                        }
                    }
                }
            ],
            "metadata": {
                "instagram": {
                    "type": "reel",
                    "shouldShareToFeed": True
                }
            }
        }
    }

    headers = {
        "Authorization": f"Bearer {BUFFER_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    response = requests.post("https://api.buffer.com", json={"query": query, "variables": variables}, headers=headers)
    result = response.json()

    if "errors" in result:
        raise Exception(f"Error de GraphQL: {result['errors']}")

    post_data = result.get("data", {}).get("createPost", {})
    if "message" in post_data:
        raise Exception(f"Error de Buffer: {post_data['message']}")

    print("🚀 Publicació enviada i publicada immediatament a Instagram!")

# --- MÒDUL DE BACKUP VIA YT-DLP ---

def process_from_backup():
    """Agafa els vídeos pendents del CSV (ordenats de més a menys likes) i els intenta publicar amb yt-dlp."""
    print("🔍 Executant Mòdul de Backup: Cerçant al CSV...")
    rows = load_backup_csv()
    
    # Filtrem els pendents (status == '')
    pending_rows = [r for r in rows if r.get('status') == '']
    
    if not pending_rows:
        print("⚠️ No hi ha cap vídeo de backup pendent al CSV.")
        return False

    for row in pending_rows:
        link = row['link']
        likes = row['likes']
        print(f"🎬 Provant backup més viral pendent: {link} ({likes} likes)...")

        try:
            # 1. Descarregar amb yt-dlp
            temp_path = download_reel_with_ytdlp(link, "temp.mp4")
            
            # 2. Processar vídeo
            output_file = process_downloaded_video(temp_path)
            
            # 3. Marcar com 'done' al CSV
            mark_link_status_in_csv(link, 'done')
            
            # 4. Pushear a GitHub i enviar a Buffer
            raw_url = push_to_github_and_get_raw_url(output_file)
            publish_to_buffer(raw_url, DEFAULT_CAPTION)
            
            print("✅ Vídeo de backup processat i publicat amb èxit!")
            return True

        except Exception as e:
            print(f"❌ Error amb el backup {link}: {e}")
            print("Marcant com 'failed' al CSV i provant el següent més viral...")
            mark_link_status_in_csv(link, 'failed')
            continue

    return False

# --- MAIN ---

def main():
    if not GITHUB_REPOSITORY:
        print("Error: La variable GITHUB_REPOSITORY no està definida.")
        return

    clean_videos_folder()

    client = ApifyClient(APIFY_TOKEN)
    accounts = load_accounts()
    if not accounts: 
        print("Error: No hi ha comptes a accounts.csv")
        return

    if os.path.exists(DB_FILE):
        with open(DB_FILE, 'r') as f: processed_ids = json.load(f)
    else: processed_ids = []

    fa_dos_dies = datetime.now(timezone.utc) - timedelta(days=2)
    video_enviat = False

    for _ in range(2):
        selected_account = random.choice(accounts)
        print(f"Provant compte: {selected_account}")

        run_input = {
            "directUrls": [selected_account],
            "resultsType": "posts",
            "resultsLimit": 3
        }

        try:
            run = client.actor("apify/instagram-api-scraper").call(run_input=run_input)
            items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
            
            candidates = []
            for i in items:
                is_video = i.get("videoUrl") or i.get("type") == "Video"
                is_new_id = i.get("id") not in processed_ids
                
                post_date_raw = i.get("timestamp") or i.get("takenAt")
                is_recent = True
                if post_date_raw:
                    try:
                        if isinstance(post_date_raw, (int, float)):
                            post_date = datetime.fromtimestamp(post_date_raw, tz=timezone.utc)
                        else:
                            post_date = datetime.fromisoformat(str(post_date_raw).replace("Z", "+00:00"))
                        if post_date < fa_dos_dies:
                            is_recent = False
                    except Exception:
                        pass
                
                if is_video and is_new_id and is_recent:
                    candidates.append(i)
            
            if candidates:
                # 1. Guardar TOTS els candidats al CSV de backup ordenats per likes
                sync_candidates_to_backup_csv(candidates)
                
                # 2. Ordenar per likes de més a menys per triar el millor d'aquesta execució
                candidates.sort(key=lambda x: x.get("likesCount", 0), reverse=True)
                
                for candidate in candidates:
                    link = candidate.get('url') or f"https://www.instagram.com/p/{candidate.get('code')}/"
                    try:
                        temp_path = "temp.mp4"
                        if download_video_file(candidate["videoUrl"], temp_path):
                            output_file = process_downloaded_video(temp_path)
                            
                            processed_ids.append(candidate["id"])
                            with open(DB_FILE, 'w') as f: json.dump(processed_ids[-500:], f)
                            
                            # Marcar com 'done' al CSV
                            mark_link_status_in_csv(link, 'done')
                            
                            raw_url = push_to_github_and_get_raw_url(output_file)
                            publish_to_buffer(raw_url, DEFAULT_CAPTION)
                            video_enviat = True
                            break
                        else:
                            mark_link_status_in_csv(link, 'failed')
                    except Exception as e:
                        print(f"⚠️ Error processant el vídeo {candidate.get('id')}: {e}")
                        mark_link_status_in_csv(link, 'failed')
                
                if video_enviat:
                    break
            else:
                print(f"No hi ha res nou a {selected_account}.")
        except Exception as e:
            print(f"Error durant el procés d'scrapping: {e}")

    # SI L'SCRAPPING DE TOTS DOS COMPTES HA FALLAT, ACTIVEM EL MÒDUL DE BACKUP CSV + YT-DLP
    if not video_enviat:
        print("⚠️ No s'ha trobat cap vídeo nou mitjançant l'scrapping. Iniciant Mòdul de Backup...")
        video_enviat = process_from_backup()

    if not video_enviat:
        print("❌ No s'ha pogut publicar cap vídeo (ni per scrapping ni per backup).")

if __name__ == "__main__":
    main()