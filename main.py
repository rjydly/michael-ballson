import os
import csv
import json
import random
import requests
from apify_client import ApifyClient
import telebot

# --- IMPORTACIÓ ROBUSTA DE MOVIEPY ---
try:
    from moviepy.editor import VideoFileClip
except (ImportError, ModuleNotFoundError):
    try:
        from moviepy import VideoFileClip
    except ImportError:
        print("Error: No s'ha pogut importar MoviePy. Revisa el requirements.txt")

# --- CONFIGURACIÓ ---
APIFY_TOKEN = os.getenv('APIFY_TOKEN')
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
CHAT_ID = os.getenv('CHAT_ID')
DB_FILE = 'processed_videos.json'
ACCOUNTS_FILE = 'accounts.csv'

def load_accounts():
    """Carrega les URLs del fitxer CSV."""
    if not os.path.exists(ACCOUNTS_FILE):
        return []
    with open(ACCOUNTS_FILE, mode='r') as f:
        # Agafa línies que continguin "instagram.com"
        return [line.strip() for line in f if "instagram.com" in line]

def main():
    # Inicialitzem clients
    client = ApifyClient(APIFY_TOKEN)
    bot = telebot.TeleBot(TELEGRAM_TOKEN)
    
    # 1. Triar un compte aleatori
    all_accounts = load_accounts()
    if not all_accounts:
        print("Error: El fitxer accounts.csv està buit o no existeix.")
        return

    selected_account = random.choice(all_accounts)
    print(f"--- Iniciant bot per al compte: {selected_account} ---")

    # 2. Carregar historial de vídeos enviats
    if os.path.exists(DB_FILE):
        with open(DB_FILE, 'r') as f:
            processed_ids = json.load(f)
    else:
        processed_ids = []

    # 3. Executar Scraper a Apify
    run_input = {
        "directUrls": [selected_account],
        "resultsType": "posts",
        "resultsLimit": 1, 
        "onlyPostsNewerThan": "1 days"
    }

    print("Cridant l'API d'Apify...")
    run = client.actor("apify/instagram-api-scraper").call(run_input=run_input)
    items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
    
    # 4. Buscar si hi ha un vídeo nou
    video_data = None
    for i in items:
        # Verifiquem que sigui un vídeo i no estigui a la nostra base de dades
        if (i.get("videoUrl") or i.get("type") == "Video") and i.get("id") not in processed_ids:
            video_data = i
            break

    if not video_data:
        print("No s'ha trobat cap vídeo nou en les últimes 24h per a aquest compte.")
        return

    v_id = video_data["id"]
    video_url = video_data.get("videoUrl")
    username = video_data.get("ownerUsername", "Instagram")

    # 5. Descarregar el vídeo temporalment
    print(f"Descarregant vídeo de @{username}...")
    res = requests.get(video_url)
    with open("temp.mp4", "wb") as f:
        f.write(res.content)

    # 6. Processar amb MoviePy (CORRECCIÓ DE CÒDECS PER A MÒBIL)
    print("Processant vídeo amb MoviePy per a compatibilitat mòbil...")
    clip = VideoFileClip("temp.mp4")
    
    # Redimensionar (compatible amb MoviePy v1 i v2)
    try:
        if hasattr(clip, "resized"):
            clip = clip.resized(height=720) # v2.x
        else:
            clip = clip.resize(height=720)  # v1.x
    except Exception as e:
        print(f"Avís: No s'ha pogut redimensionar, s'enviarà original. Error: {e}")

    # Escriptura forçant el format yuv420p (vital per a la reproducció en mòbils)
    clip.write_videofile(
        "out.mp4", 
        codec="libx264", 
        audio_codec="aac",
        ffmpeg_params=["-pix_fmt", "yuv420p"] # <--- AIXÒ ARREGLA EL TEU ERROR
    )
    clip.close()

    # 7. Enviar a Telegram
    print("Enviant vídeo a Telegram...")
    with open("out.mp4", "rb") as v:
        bot.send_video(
            CHAT_ID, 
            v, 
            caption=f"🔥 Nou vídeo de @{username}\n🔗 {selected_account}"
        )

    # 8. Guardar l'ID per no repetir-lo la propera vegada
    processed_ids.append(v_id)
    # Mantenim només els últims 500 IDs per no fer el fitxer gegant
    with open(DB_FILE, 'w') as f:
        json.dump(processed_ids[-500:], f)
    
    print("Fet! Vídeo enviat i base de dades actualitzada.")

if __name__ == "__main__":
    main()