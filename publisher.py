import os
import csv
import json
import time
import requests
import subprocess
import yt_dlp

# --- IMPORTACIÓ ROBUSTA DE MOVIEPY ---
try:
    from moviepy.editor import VideoFileClip, ImageClip, ColorClip, CompositeVideoClip, concatenate_videoclips
except (ImportError, ModuleNotFoundError):
    try:
        from moviepy import VideoFileClip, ImageClip, ColorClip, CompositeVideoClip, concatenate_videoclips
    except ImportError:
        print("Error: No s'ha trobat MoviePy.")

# --- CONFIGURACIÓ ---
BUFFER_ACCESS_TOKEN = os.getenv('BUFFER_ACCESS_TOKEN')
BUFFER_CHANNEL_ID = os.getenv('BUFFER_CHANNEL_ID')
GITHUB_REPOSITORY = os.getenv('GITHUB_REPOSITORY')

DEFAULT_CAPTION = "Tonight, V stepped into the crowd, taking in live performances at Vogue World: Hollywood. Known for his own standout fashion moments, he kept it effortlessly stylish in a look worthy of the runway."

DB_FILE = 'processed_videos.json'
BACKUP_CSV = 'backup_reels.csv'
QUEUE_FILE = 'today_queue.json'
VIDEOS_DIR = 'videos'

def clean_videos_folder():
    if not os.path.exists(VIDEOS_DIR):
        os.makedirs(VIDEOS_DIR)
    else:
        for filename in os.listdir(VIDEOS_DIR):
            file_path = os.path.join(VIDEOS_DIR, filename)
            if os.path.isfile(file_path):
                os.remove(file_path)

def load_backup_csv():
    if not os.path.exists(BACKUP_CSV):
        return []
    rows = []
    with open(BACKUP_CSV, mode='r', newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows

def save_backup_csv(rows):
    for r in rows:
        try:
            r['likes'] = int(r.get('likes', 0))
        except (ValueError, TypeError):
            r['likes'] = 0

    rows.sort(key=lambda x: x['likes'], reverse=True)

    fieldnames = ['link', 'likes', 'status']
    with open(BACKUP_CSV, mode='w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)

def mark_link_status_in_csv(link, status):
    rows = load_backup_csv()
    for r in rows:
        if r['link'] == link:
            r['status'] = status
            break
    save_backup_csv(rows)

def download_video_file(url, target_path):
    if not url:
        return False
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "*/*"
    }
    for attempt in range(1, 4):
        try:
            res = requests.get(url, headers=headers, timeout=30, stream=True)
            res.raise_for_status()
            with open(target_path, "wb") as f:
                for chunk in res.iter_content(chunk_size=8192):
                    f.write(chunk)
            return True
        except Exception:
            time.sleep(2)
    return False

def download_reel_with_ytdlp(reel_url, target_path="temp.mp4"):
    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': target_path,
        'quiet': True,
        'overwrites': True
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([reel_url])
    return target_path

def fit_clip_to_1080x1920(clip):
    target_w, target_h = 1080, 1920
    w, h = clip.size
    
    scale = min(target_w / w, target_h / h)
    new_w = int(w * scale)
    new_h = int(h * scale)
    if new_w % 2 != 0: new_w -= 1
    if new_h % 2 != 0: new_h -= 1

    resized_clip = clip.resized(new_size=(new_w, new_h)) if hasattr(clip, "resized") else clip.resize(new_size=(new_w, new_h))
    
    dur = clip.duration if clip.duration else 0.1
    if hasattr(ColorClip, "with_duration"):
        bg = ColorClip(size=(target_w, target_h), color=(0, 0, 0)).with_duration(dur)
    else:
        bg = ColorClip(size=(target_w, target_h), color=(0, 0, 0)).set_duration(dur)

    positioned_clip = resized_clip.with_position("center") if hasattr(resized_clip, "with_position") else resized_clip.set_position("center")
    
    composite = CompositeVideoClip([bg, positioned_clip], size=(target_w, target_h))
    return composite.with_duration(dur) if hasattr(composite, "with_duration") else composite.set_duration(dur)

def process_downloaded_video(local_file_path):
    print("Processant vídeo a 1080x1920 (fons negre) amb portada al primer frame...")
    clip = VideoFileClip(local_file_path)
    
    main_video = fit_clip_to_1080x1920(clip)

    thumb_path = os.path.join("assets", "thumbnail.png")
    if os.path.exists(thumb_path):
        img = ImageClip(thumb_path)
        img_duration = img.with_duration(0.1) if hasattr(img, "with_duration") else img.set_duration(0.1)
        thumb_clip = fit_clip_to_1080x1920(img_duration)
        final_clip = concatenate_videoclips([thumb_clip, main_video])
    else:
        final_clip = main_video

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
    if os.path.exists(thumb_path): final_clip.close()
    if os.path.exists(local_file_path): os.remove(local_file_path)

    file_size_mb = os.path.getsize(output_path) / (1024 * 1024)
    if file_size_mb > 48:
        raise Exception(f"El vídeo pesa massa ({file_size_mb:.2f} MB).")

    return output_path

def push_to_github_and_get_raw_url(filepath):
    subprocess.run(["git", "config", "--local", "user.email", "bot@github.com"], check=True)
    subprocess.run(["git", "config", "--local", "user.name", "ViralBot"], check=True)
    
    subprocess.run(["git", "add", "-f", filepath], check=True)
    subprocess.run(["git", "add", DB_FILE], check=True)
    subprocess.run(["git", "add", QUEUE_FILE], check=True)
    subprocess.run(["git", "add", BACKUP_CSV], check=True)
    
    commit_res = subprocess.run(["git", "commit", "-m", "Publicació realitzada [skip ci]"])
    if commit_res.returncode == 0:
        subprocess.run(["git", "push"], check=True)
        time.sleep(5)
    
    filename = os.path.basename(filepath)
    return f"https://raw.githubusercontent.com/{GITHUB_REPOSITORY}/main/videos/{filename}"

def publish_to_buffer(video_public_url, caption):
    query = """
    mutation CreatePost($input: CreatePostInput!) {
      createPost(input: $input) {
        ... on PostActionSuccess { post { id } }
        ... on MutationError { message }
      }
    }
    """
    variables = {
        "input": {
            "text": caption,
            "channelId": BUFFER_CHANNEL_ID,
            "schedulingType": "automatic",
            "mode": "shareNow",
            "assets": [{"video": {"url": video_public_url, "metadata": {"thumbnailOffset": 0}}}],
            "metadata": {"instagram": {"type": "reel", "shouldShareToFeed": True}}
        }
    }
    headers = {"Authorization": f"Bearer {BUFFER_ACCESS_TOKEN}", "Content-Type": "application/json"}
    res = requests.post("https://api.buffer.com", json={"query": query, "variables": variables}, headers=headers).json()
    
    if "errors" in res: raise Exception(f"Error GraphQL: {res['errors']}")
    post_data = res.get("data", {}).get("createPost", {})
    if "message" in post_data: raise Exception(f"Error Buffer: {post_data['message']}")

    print("🚀 Publicat directament a Instagram!")

def process_from_backup():
    print("🔍 Cua diària buida. Iniciant Mòdul de Backup CSV...")
    rows = load_backup_csv()
    pending_rows = [r for r in rows if not r.get('status', '').strip()]
    
    if not pending_rows:
        print("⚠️ No hi ha cap vídeo pendent al CSV de backup.")
        return False

    consecutive_failures = 0
    pause_count = 0

    for row in pending_rows:
        link = row['link']
        print(f"🎬 Provant backup: {link} ({row['likes']} likes)...")
        
        try:
            temp_path = download_reel_with_ytdlp(link, "temp.mp4")
            output_file = process_downloaded_video(temp_path)
            mark_link_status_in_csv(link, 'done')
            
            raw_url = push_to_github_and_get_raw_url(output_file)
            publish_to_buffer(raw_url, DEFAULT_CAPTION)
            return True

        except Exception as e:
            print(f"❌ Error descarregant/processant backup {link}: {e}")
            mark_link_status_in_csv(link, 'failed')
            consecutive_failures += 1

            if consecutive_failures >= 2:
                if pause_count < 2:
                    pause_count += 1
                    print(f"⚠️ Detectades 2 fallades consecutives. Esperant 5 minuts (Pausa {pause_count}/2)...")
                    time.sleep(300)
                    consecutive_failures = 0
                else:
                    print("🛑 S'abandona el procés per no marcar la resta del CSV com a 'failed'.")
                    return False

            continue

    return False

def main():
    clean_videos_folder()

    if os.path.exists(DB_FILE):
        with open(DB_FILE, 'r') as f: processed_ids = json.load(f)
    else: processed_ids = []

    video_enviat = False

    if os.path.exists(QUEUE_FILE):
        with open(QUEUE_FILE, 'r', encoding='utf-8') as f:
            today_queue = json.load(f)

        while today_queue:
            candidate = today_queue.pop(0)
            video_id = candidate.get("id")
            
            if video_id in processed_ids:
                continue

            username = candidate.get("username") or candidate.get("ownerUsername") or "desconegut"
            likes = candidate.get("likes") if "likes" in candidate else candidate.get("likesCount", 0)
            print(f"🎬 Publicant vídeo de la cua diària: @{username} ({likes} likes)")
            
            try:
                temp_path = "temp.mp4"
                if not download_video_file(candidate.get("videoUrl"), temp_path):
                    reel_link = candidate.get("url") or f"https://www.instagram.com/p/{candidate.get('code')}/"
                    download_reel_with_ytdlp(reel_link, temp_path)

                output_file = process_downloaded_video(temp_path)
                
                processed_ids.append(video_id)
                with open(DB_FILE, 'w') as f: json.dump(processed_ids[-500:], f)
                with open(QUEUE_FILE, 'w', encoding='utf-8') as f: json.dump(today_queue, f, indent=2)

                raw_url = push_to_github_and_get_raw_url(output_file)
                publish_to_buffer(raw_url, DEFAULT_CAPTION)
                video_enviat = True
                break

            except Exception as e:
                print(f"⚠️ Error processant vídeo de la cua {video_id}: {e}")
                continue

    if not video_enviat:
        video_enviat = process_from_backup()

    if not video_enviat:
        print("❌ No s'ha pogut publicar cap vídeo.")

if __name__ == "__main__":
    main()