import os
import csv
import json
import time
import random
import requests
import subprocess
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

# Variable per al text de la publicació (es pot canviar manualment des d'aquí)
DEFAULT_CAPTION = "Tonight, V stepped into the crowd, taking in live performances at Vogue World: Hollywood. Known for his own standout fashion moments, he kept it effortlessly stylish in a look worthy of the runway."

DB_FILE = 'processed_videos.json'
ACCOUNTS_FILE = 'accounts.csv'
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

def process_video(video_url):
    """Descarrega el vídeo, afegeix la thumbnail al frame 0 i el guarda a videos/out.mp4."""
    print("Descarregant vídeo...")
    res = requests.get(video_url)
    temp_path = "temp.mp4"
    with open(temp_path, "wb") as f:
        f.write(res.content)

    print("Processant vídeo a 1080p i afegint la portada al primer frame...")
    clip = VideoFileClip(temp_path)
    
    # Calcular dimensions parelles a 1080p
    target_h = 1080
    w, h = clip.size
    target_w = int(w * (target_h / h))
    if target_w % 2 != 0: target_w -= 1

    # Redimensionar el vídeo principal
    if hasattr(clip, "resized"):
        clip = clip.resized(new_size=(target_w, target_h))
    else:
        clip = clip.resize(new_size=(target_w, target_h))

    # Afegeix la thumbnail d'assets/thumbnail.png al primer frame
    thumb_path = os.path.join("assets", "thumbnail.png")
    if os.path.exists(thumb_path):
        img = ImageClip(thumb_path)
        thumb_clip = img.with_duration(0.1) if hasattr(img, "with_duration") else img.set_duration(0.1)
        thumb_clip = thumb_clip.resized(new_size=(target_w, target_h)) if hasattr(thumb_clip, "resized") else thumb_clip.resize(new_size=(target_w, target_h))
        final_clip = concatenate_videoclips([thumb_clip, clip])
    else:
        print("⚠️ Avís: No s'ha trobat assets/thumbnail.png. Es processarà sense portada.")
        final_clip = clip

    # Guardar a la carpeta videos/
    output_path = os.path.join(VIDEOS_DIR, "out.mp4")
    final_clip.write_videofile(
        output_path, 
        codec="libx264", 
        audio_codec="aac",
        audio=True,
        temp_audiofile='temp-audio.m4a',
        remove_temp=True,
        ffmpeg_params=["-pix_fmt", "yuv420p"]
    )
    clip.close()
    if os.path.exists(thumb_path):
        final_clip.close()
    if os.path.exists(temp_path):
        os.remove(temp_path)

    return output_path

def push_to_github_and_get_raw_url(filepath):
    """Pushea el nou vídeo a GitHub (forçant el fitxer .mp4) i retorna la URL Raw de la branca main."""
    print("Pusheant el nou vídeo a GitHub...")
    
    subprocess.run(["git", "config", "--local", "user.email", "bot@github.com"], check=True)
    subprocess.run(["git", "config", "--local", "user.name", "ViralBot"], check=True)
    
    subprocess.run(["git", "add", "-f", filepath], check=True)
    subprocess.run(["git", "add", DB_FILE], check=True)
    
    commit_res = subprocess.run(["git", "commit", "-m", "Actualitzar vídeo per a Buffer [skip ci]"])
    if commit_res.returncode == 0:
        subprocess.run(["git", "push"], check=True)
        print("Esperant 5 segons per a la propagació de GitHub Raw...")
        time.sleep(5)
    
    filename = os.path.basename(filepath)
    raw_url = f"https://raw.githubusercontent.com/{GITHUB_REPOSITORY}/main/videos/{filename}"
    print(f"🔗 URL pública de GitHub generada: {raw_url}")
    return raw_url

def publish_to_buffer(video_public_url, caption):
    """Publica el vídeo a la cua de Buffer utilitzant el primer frame com a portada i especifica el tipus 'reel'."""
    print("Enviant a la cua de Buffer...")
    
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
            "mode": "addToQueue",
            "assets": [
                {
                    "video": {
                        "url": video_public_url,
                        "metadata": {
                            "thumbnailOffset": 0  # Frame 0 (thumbnail.png)
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

    print("✅ Publicació enviada correctament a la cua de Buffer!")

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

    video_enviat = False
    for _ in range(2):
        selected_account = random.choice(accounts)
        print(f"Provant compte: {selected_account}")

        run_input = {
            "directUrls": [selected_account],
            "resultsType": "posts",
            "resultsLimit": 3, 
            "onlyPostsNewerThan": "2 days"
        }

        try:
            run = client.actor("apify/instagram-api-scraper").call(run_input=run_input)
            items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
            
            candidates = [i for i in items if (i.get("videoUrl") or i.get("type") == "Video") and i.get("id") not in processed_ids]
            
            if candidates:
                candidates.sort(key=lambda x: x.get("likesCount", 0), reverse=True)
                best_video = candidates[0]
                
                output_file = process_video(best_video["videoUrl"])
                
                processed_ids.append(best_video["id"])
                with open(DB_FILE, 'w') as f: json.dump(processed_ids[-500:], f)
                
                raw_url = push_to_github_and_get_raw_url(output_file)
                
                # Fent servir el caption per defecte configurat al principi
                publish_to_buffer(raw_url, DEFAULT_CAPTION)
                
                video_enviat = True
                break
            else:
                print(f"No hi ha res nou a {selected_account}.")
        except Exception as e:
            print(f"Error durant el procés: {e}")

    if not video_enviat:
        print("No s'ha trobat cap vídeo nou per enviar.")

if __name__ == "__main__":
    main()