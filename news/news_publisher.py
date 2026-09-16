import os
import re
import csv
import json
import html
import time
import subprocess
import requests
import numpy as np
from PIL import Image, ImageDraw, ImageFont

# ==============================================================================
# CONFIGURACIÓ PRINCIPAL
# ==============================================================================
# True  -> Només genera el carrousel i l'envia a Telegram (mode test).
# False -> Publica a Instagram + Facebook via Buffer, sincronitza amb GitHub i envia a Telegram.
MODE_PROVA = False

ACCOUNT_NAME = "@homer.news"
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NEWS_DIR = os.path.join(BASE_DIR, "news")
CSV_FILE = os.path.join(NEWS_DIR, "news_database.csv")
IMAGES_DIR = os.path.join(BASE_DIR, "images")
ASSETS_DIR = os.path.join(BASE_DIR, "assets")

LOGO_PATH = os.path.join(ASSETS_DIR, "logo.png")
FONT_PATH = os.path.join(ASSETS_DIR, "Anton-Regular.ttf")
OUTRO_BG_PATH = os.path.join(ASSETS_DIR, "background_news.png")

SERPER_API_KEY = os.getenv("SERPER_API_KEY")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
BUFFER_ACCESS_TOKEN = os.getenv("BUFFER_ACCESS_TOKEN")
BUFFER_CHANNEL_ID = os.getenv("BUFFER_CHANNEL_ID")          # Canal d'Instagram
BUFFER_FB_CHANNEL_ID = os.getenv("BUFFER_FB_CHANNEL_ID")    # Pàgina de Facebook
GITHUB_REPOSITORY = os.getenv("GITHUB_REPOSITORY")


def ensure_workspace():
    """Assegura l'existència de les carpetes de treball necessàries."""
    os.makedirs(ASSETS_DIR, exist_ok=True)
    os.makedirs(IMAGES_DIR, exist_ok=True)
    os.makedirs(NEWS_DIR, exist_ok=True)


def ensure_font_exists():
    """Descarrega la font Anton de Google Fonts si no existeix a assets."""
    ensure_workspace()
    if not os.path.exists(FONT_PATH):
        print("⬇️ Descarregant font Anton de Google Fonts...")
        font_url = "https://raw.githubusercontent.com/google/fonts/main/ofl/anton/Anton-Regular.ttf"
        res = requests.get(font_url, timeout=15)
        with open(FONT_PATH, "wb") as f:
            f.write(res.content)
    return FONT_PATH


def get_next_pending_news():
    """Llegeix el CSV i retorna la primera notícia amb status buit."""
    if not os.path.exists(CSV_FILE):
        raise Exception(f"No s'ha trobat el fitxer {CSV_FILE}!")

    rows = []
    with open(CSV_FILE, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)

    for row in rows:
        if not row.get("status", "").strip():
            return row, rows

    return None, rows


def mark_news_as_done(news_id, rows):
    """Marca la fila de la notícia com a 'done' al CSV."""
    for r in rows:
        if str(r["id"]) == str(news_id):
            r["status"] = "done"
            break

    fieldnames = ["id", "headline_1", "query_1", "headline_2", "query_2", "headline_3", "query_3", "caption", "status"]
    with open(CSV_FILE, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(rows)


# --- DETECCIÓ I ELIMINACIÓ DE FRANGES SÒLIDES (LETTERBOXING) ---
def remove_solid_letterboxes(img, std_threshold=6.0, max_crop_ratio=0.25):
    """
    Detecta i retalla automàticament franges de color sòlid uniforme (blanques, negres, etc.)
    que envolten la imatge a causa de captures de pantalla o marcs de memes.
    """
    arr = np.array(img.convert("RGB"))
    h, w, _ = arr.shape

    # 1. Analitzar part superior (Top)
    top = 0
    max_top = int(h * max_crop_ratio)
    for y in range(max_top):
        row = arr[y, :, :]
        if np.std(row) < std_threshold:
            top = y + 1
        else:
            break

    # 2. Analitzar part inferior (Bottom)
    bottom = h
    min_bottom = int(h * (1 - max_crop_ratio))
    for y in range(h - 1, min_bottom, -1):
        row = arr[y, :, :]
        if np.std(row) < std_threshold:
            bottom = y
        else:
            break

    # 3. Analitzar lateral esquerre (Left)
    left = 0
    max_left = int(w * max_crop_ratio)
    for x in range(max_left):
        col = arr[:, x, :]
        if np.std(col) < std_threshold:
            left = x + 1
        else:
            break

    # 4. Analitzar lateral dret (Right)
    right = w
    min_right = int(w * (1 - max_crop_ratio))
    for x in range(w - 1, min_right, -1):
        col = arr[:, x, :]
        if np.std(col) < std_threshold:
            right = x
        else:
            break

    if top > 0 or bottom < h or left > 0 or right < w:
        print(f"✂️ Retallades franges sòlides: Top={top}px, Bottom={h-bottom}px, Left={left}px, Right={w-right}px")
        img = img.crop((left, top, right, bottom))

    return img


# --- DESCÀRREGA D'IMATGES VIA SERPER (GOOGLE IMAGES) ---
def search_and_download_image(query, target_filename):
    """Cerca imatges d'alta qualitat a Google filtrant bancs de pagament amb marca d'aigua."""
    print(f"🔍 Cercant a Google Images via Serper: '{query}'...")
    
    clean_query = f"{query} -alamy -gettyimages -shutterstock -istockphoto -dreamstime"
    url = "https://google.serper.dev/images"
    payload = json.dumps({"q": clean_query, "num": 8})
    headers = {
        'X-API-KEY': SERPER_API_KEY,
        'Content-Type': 'application/json'
    }

    images = []
    try:
        response = requests.post(url, headers=headers, data=payload, timeout=15)
        data = response.json()
        images = data.get("images", [])
    except Exception as e:
        print(f"⚠️ Error connectant amb Serper API: {e}")

    dl_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    }

    banned = ["alamy.com", "gettyimages", "shutterstock", "istockphoto", "dreamstime", "stockphoto"]
    for img_obj in images:
        img_url = img_obj.get("imageUrl")
        if not img_url or any(b in img_url.lower() for b in banned):
            continue

        try:
            r = requests.get(img_url, headers=dl_headers, timeout=12)
            if r.status_code == 200 and len(r.content) > 15000:
                with open(target_filename, "wb") as f:
                    f.write(r.content)
                with Image.open(target_filename) as test_img:
                    test_img.verify()
                print(f"✅ Imatge descarregada: {img_url[:60]}...")
                return target_filename
        except Exception:
            continue

    print(f"⚠️ No s'ha trobat cap imatge vàlida. Fent servir fons d'estudi per a '{query}'.")
    fallback_img = Image.new("RGB", (1080, 1350), color=(25, 25, 30))
    fallback_img.save(target_filename)
    return target_filename


# --- MOTOR GRÀFIC PILLOW ---
def parse_headline_words(headline_text):
    """Identifica paraules envoltades amb ** per pintar-les de groc."""
    tokens = re.split(r'(\*\*.*?\*\*)', headline_text)
    parsed = []
    for token in tokens:
        if token.startswith("**") and token.endswith("**"):
            words = token[2:-2].strip().split()
            for w in words:
                if w: parsed.append((w.upper(), True))
        else:
            words = token.strip().split()
            for w in words:
                if w: parsed.append((w.upper(), False))
    return parsed


def wrap_words_to_lines(parsed_words, font, max_width, draw):
    """Ajusta les paraules a línies respectant l'amplada màxima del llenç."""
    space_w = draw.textbbox((0, 0), " ", font=font)[2]
    lines, current_line, current_w = [], [], 0

    for word, is_highlight in parsed_words:
        bbox = draw.textbbox((0, 0), word, font=font)
        w = bbox[2] - bbox[0]

        if current_w + (space_w if current_line else 0) + w <= max_width:
            current_line.append((word, is_highlight, w))
            current_w += (space_w if len(current_line) > 1 else 0) + w
        else:
            if current_line:
                lines.append(current_line)
            current_line = [(word, is_highlight, w)]
            current_w = w

    if current_line:
        lines.append(current_line)
    return lines


def draw_footer_with_arrow(draw, canvas_w, canvas_h, text, font, draw_arrow=True):
    """Dibuixa el text del peu acompanyat d'una fletxa vectorial estilitzada."""
    color = (175, 175, 175)
    bbox = draw.textbbox((0, 0), text, font=font)
    txt_w = bbox[2] - bbox[0]
    txt_h = bbox[3] - bbox[1]

    gap = 14
    arrow_w = 26
    total_w = txt_w + (gap + arrow_w if draw_arrow else 0)
    start_x = (canvas_w - total_w) // 2
    base_y = canvas_h - 55

    draw.text((start_x, base_y), text, font=font, fill=color)

    if draw_arrow:
        ax = start_x + txt_w + gap
        ay = base_y + (txt_h // 2) + 2

        # Línia central de la fletxa
        draw.line([(ax, ay), (ax + arrow_w - 6, ay)], fill=color, width=3)
        # Capçalera triangular neta
        head_len = 9
        head_h = 6
        points = [
            (ax + arrow_w, ay),
            (ax + arrow_w - head_len, ay - head_h),
            (ax + arrow_w - head_len, ay + head_h)
        ]
        draw.polygon(points, fill=color)


def render_slide(source_image_path, headline_raw, footer_text, output_path, has_arrow=False):
    """Renderitza les diapositives 1, 2 i 3 amb degradat, logo, línies i retall net."""
    CANVAS_W, CANVAS_H = 1080, 1350
    font_file = ensure_font_exists()

    font_size = 74
    font_headline = ImageFont.truetype(font_file, font_size)
    font_footer = ImageFont.truetype(font_file, 26)
    font_fallback_logo = ImageFont.truetype(font_file, 44)

    # 1. Carregar imatge i eliminar barres blanques/negres
    raw_img = Image.open(source_image_path).convert("RGBA")
    cleaned_img = remove_solid_letterboxes(raw_img)

    img_ratio = cleaned_img.width / cleaned_img.height
    canvas_ratio = CANVAS_W / CANVAS_H
    if img_ratio > canvas_ratio:
        nh = CANVAS_H
        nw = int(CANVAS_H * img_ratio)
    else:
        nw = CANVAS_W
        nh = int(CANVAS_W / img_ratio)

    img = cleaned_img.resize((nw, nh), Image.Resampling.LANCZOS)
    left = (nw - CANVAS_W) // 2

    # Retall superior (Top-Bias) per protegir les cares dels subjectes
    top = int((nh - CANVAS_H) * 0.10) if nh > CANVAS_H else 0
    img = img.crop((left, top, left + CANVAS_W, top + CANVAS_H))

    temp_draw = ImageDraw.Draw(img)
    max_text_w = CANVAS_W - 140

    parsed_words = parse_headline_words(headline_raw)
    lines = wrap_words_to_lines(parsed_words, font_headline, max_text_w, temp_draw)

    line_h = int(font_size * 1.12)
    total_text_h = len(lines) * line_h
    
    bottom_margin = 120
    text_start_y = CANVAS_H - bottom_margin - total_text_h
    separator_y = text_start_y - 95

    # 2. Degradat negre profund
    gradient = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 0))
    draw_g = ImageDraw.Draw(gradient)

    gradient_top = int(CANVAS_H * 0.28)
    for y in range(gradient_top, CANVAS_H):
        progress = (y - gradient_top) / (CANVAS_H - gradient_top)
        alpha = int(255 * (progress ** 1.15))
        draw_g.line([(0, y), (CANVAS_W, y)], fill=(0, 0, 0, min(255, alpha)))

    final_img = Image.alpha_composite(img, gradient).convert("RGBA")
    draw = ImageDraw.Draw(final_img)

    # 3. Logo central i línies separadores
    side_margin = 60
    logo_drawn = False

    if os.path.exists(LOGO_PATH):
        try:
            logo_img = Image.open(LOGO_PATH).convert("RGBA")
            target_h = 110
            aspect = logo_img.width / logo_img.height
            target_w = int(target_h * aspect)
            if target_w > 360:
                target_w = 360
                target_h = int(target_w / aspect)

            logo_resized = logo_img.resize((target_w, target_h), Image.Resampling.LANCZOS)
            logo_x = (CANVAS_W - target_w) // 2
            logo_y = separator_y - (target_h // 2)

            line_padding = 30
            draw.line([(side_margin, separator_y), (logo_x - line_padding, separator_y)], fill=(210, 210, 210, 220), width=3)
            draw.line([(logo_x + target_w + line_padding, separator_y), (CANVAS_W - side_margin, separator_y)], fill=(210, 210, 210, 220), width=3)
            final_img.alpha_composite(logo_resized, (logo_x, logo_y))
            logo_drawn = True
        except Exception as e:
            print(f"⚠️ Avís amb el logo: {e}")

    if not logo_drawn:
        fallback_txt = ACCOUNT_NAME.upper()
        bbox = draw.textbbox((0, 0), fallback_txt, font=font_fallback_logo)
        txt_w, txt_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        txt_x = (CANVAS_W - txt_w) // 2
        txt_y = separator_y - (txt_h // 2) - 4
        draw.line([(side_margin, separator_y), (txt_x - 25, separator_y)], fill=(210, 210, 210, 220), width=3)
        draw.line([(txt_x + txt_w + 25, separator_y), (CANVAS_W - side_margin, separator_y)], fill=(210, 210, 210, 220), width=3)
        draw.text((txt_x, txt_y), fallback_txt, font=font_fallback_logo, fill=(230, 230, 230))

    # 4. Text del titular
    space_w = draw.textbbox((0, 0), " ", font=font_headline)[2]
    current_y = text_start_y
    for line in lines:
        line_w = sum(w for _, _, w in line) + (len(line) - 1) * space_w
        cur_x = (CANVAS_W - line_w) // 2
        for word, is_highlight, w in line:
            color = (255, 230, 0) if is_highlight else (255, 255, 255)
            draw.text((cur_x, current_y), word, font=font_headline, fill=color)
            cur_x += w + space_w
        current_y += line_h

    # 5. Peu de pàgina amb fletxa vectorial
    draw_footer_with_arrow(draw, CANVAS_W, CANVAS_H, footer_text, font_footer, draw_arrow=has_arrow)

    final_img.convert("RGB").save(output_path, quality=95)
    return output_path


def render_outro_slide(bg_image_path, headline_raw, footer_text, output_path):
    """Renderitza la Slide 4: logo ampliat + text centrat amb contorn negre (stroke)."""
    CANVAS_W, CANVAS_H = 1080, 1350
    font_file = ensure_font_exists()

    font_size = 76
    font_headline = ImageFont.truetype(font_file, font_size)
    font_footer = ImageFont.truetype(font_file, 26)
    font_fallback_logo = ImageFont.truetype(font_file, 58)

    # 1. Carregar i retallar fons a proporció 4:5
    img = Image.open(bg_image_path).convert("RGBA")
    img_ratio = img.width / img.height
    canvas_ratio = CANVAS_W / CANVAS_H
    if img_ratio > canvas_ratio:
        nh = CANVAS_H
        nw = int(CANVAS_H * img_ratio)
    else:
        nw = CANVAS_W
        nh = int(CANVAS_W / img_ratio)

    img = img.resize((nw, nh), Image.Resampling.LANCZOS)
    left = (nw - CANVAS_W) // 2
    top = (nh - CANVAS_H) // 2
    img = img.crop((left, top, left + CANVAS_W, top + CANVAS_H))

    final_img = img.copy()
    draw = ImageDraw.Draw(final_img)

    # 2. Parsejar i calcular el bloc de text
    temp_draw = ImageDraw.Draw(final_img)
    max_text_w = CANVAS_W - 140
    parsed_words = parse_headline_words(headline_raw)
    lines = wrap_words_to_lines(parsed_words, font_headline, max_text_w, temp_draw)

    line_h = int(font_size * 1.15)
    text_total_h = len(lines) * line_h

    # 3. Logo ampliat per a l'outro (target_h = 200px)
    logo_drawn = False
    logo_w, logo_h = 0, 0
    logo_resized = None

    if os.path.exists(LOGO_PATH):
        try:
            logo_img = Image.open(LOGO_PATH).convert("RGBA")
            target_h = 200
            aspect = logo_img.width / logo_img.height
            target_w = int(target_h * aspect)
            if target_w > 480:
                target_w = 480
                target_h = int(target_w / aspect)

            logo_resized = logo_img.resize((target_w, target_h), Image.Resampling.LANCZOS)
            logo_w, logo_h = target_w, target_h
            logo_drawn = True
        except Exception as e:
            print(f"⚠️ Avís amb el logo ampliat: {e}")

    if not logo_drawn:
        fallback_txt = ACCOUNT_NAME.upper()
        bbox = draw.textbbox((0, 0), fallback_txt, font=font_fallback_logo)
        logo_w = bbox[2] - bbox[0]
        logo_h = bbox[3] - bbox[1]

    # 4. Agrupació estil Canva: Centrar [Logo + Espai + Text] al mig exacte de la pantalla
    gap = 48
    total_group_h = logo_h + gap + text_total_h
    group_start_y = (CANVAS_H - total_group_h) // 2

    # Pintar logo centrat horitzontalment
    logo_x = (CANVAS_W - logo_w) // 2
    logo_y = group_start_y

    if logo_drawn and logo_resized:
        final_img.alpha_composite(logo_resized, (logo_x, logo_y))
    else:
        draw.text((logo_x, logo_y), ACCOUNT_NAME.upper(), font=font_fallback_logo, fill=(235, 235, 235))

    # Pintar text sota el logo AMB CONTORN NEGRE (stroke)
    space_w = draw.textbbox((0, 0), " ", font=font_headline)[2]
    current_y = logo_y + logo_h + gap

    for line in lines:
        line_w = sum(w for _, _, w in line) + (len(line) - 1) * space_w
        cur_x = (CANVAS_W - line_w) // 2
        for word, is_highlight, w in line:
            color = (255, 230, 0) if is_highlight else (255, 255, 255)
            # stroke_width=4 i stroke_fill=(0, 0, 0) per a un contorn negre nítid
            draw.text(
                (cur_x, current_y),
                word,
                font=font_headline,
                fill=color,
                stroke_width=4,
                stroke_fill=(0, 0, 0)
            )
            cur_x += w + space_w
        current_y += line_h

    # 5. Peu inferior
    if footer_text:
        fb_bbox = draw.textbbox((0, 0), footer_text, font=font_footer)
        fb_w = fb_bbox[2] - fb_bbox[0]
        draw.text(
            ((CANVAS_W - fb_w) // 2, CANVAS_H - 55),
            footer_text,
            font=font_footer,
            fill=(200, 200, 200),
            stroke_width=2,
            stroke_fill=(0, 0, 0)
        )

    final_img.convert("RGB").save(output_path, quality=95)
    return output_path


# --- GIT I BUFFER ---
def push_carousel_to_github(image_paths, news_id):
    """Puja les 4 imatges del carrousel i el CSV a GitHub amb URLs úniques."""
    print("🌐 Sincronitzant carrousel i CSV amb GitHub...")
    subprocess.run(["git", "config", "--local", "user.email", "bot@github.com"], check=True)
    subprocess.run(["git", "config", "--local", "user.name", "NewsBot"], check=True)
    subprocess.run(["git", "pull", "--rebase", "origin", "main"], check=False)

    for img_p in image_paths:
        subprocess.run(["git", "add", "-f", img_p], check=True)
    subprocess.run(["git", "add", CSV_FILE], check=True)

    commit_res = subprocess.run(["git", "commit", "-m", f"Publicat carrousel notícia #{news_id} [skip ci]"])
    if commit_res.returncode == 0:
        subprocess.run(["git", "push", "origin", "main"], check=True)
        time.sleep(3)

    public_urls = []
    ts = int(time.time())
    for img_p in image_paths:
        fname = os.path.basename(img_p)
        public_urls.append(f"https://raw.githubusercontent.com/{GITHUB_REPOSITORY}/main/images/{fname}?t={ts}")
    return public_urls


def publish_carousel_to_buffer(image_urls, caption, channel_id, platform="instagram"):
    """Publica el carrousel a Instagram o Facebook via Buffer."""
    if not channel_id:
        print(f"⚠️ Channel ID per a {platform} no està configurat a les variables d'entorn! S'omet.")
        return

    print(f"🚀 Publicant Carrousel a {platform.capitalize()}...")
    query = """
    mutation CreatePost($input: CreatePostInput!) {
      createPost(input: $input) {
        ... on PostActionSuccess { post { id } }
        ... on MutationError { message }
      }
    }
    """
    assets_payload = [{"image": {"url": u}} for u in image_urls]
    
    # Tant Instagram com Facebook utilitzen type = "post" a l'API de Buffer.
    # En rebre múltiples fotos a 'assets', Buffer i Instagram el publiquen com a carrousel.
    metadata_payload = (
        {"instagram": {"type": "post", "shouldShareToFeed": True}}
        if platform == "instagram"
        else {"facebook": {"type": "post"}}
    )

    variables = {
        "input": {
            "text": caption,
            "channelId": channel_id,
            "schedulingType": "automatic",
            "mode": "shareNow",
            "assets": assets_payload,
            "metadata": metadata_payload
        }
    }
    headers = {"Authorization": f"Bearer {BUFFER_ACCESS_TOKEN}", "Content-Type": "application/json"}
    
    res = requests.post("https://api.buffer.com", json={"query": query, "variables": variables}, headers=headers, timeout=25).json()

    if "errors" in res:
        raise Exception(f"Error GraphQL Buffer ({platform}): {res['errors']}")
    
    post_data = res.get("data", {}).get("createPost", {})
    if "message" in post_data:
        raise Exception(f"Error Buffer ({platform}): {post_data['message']}")

    post_id = post_data.get("post", {}).get("id", "Desconegut")
    print(f"✅ Carrousel publicat amb èxit a {platform.capitalize()}! ID del post: {post_id}")


def send_telegram_carousel(image_paths, caption, is_published=False):
    """Envia un àlbum natiu de fotos a Telegram amb el text adjunt a la primera slide."""
    if not TELEGRAM_TOKEN or not CHAT_ID:
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMediaGroup"
    prefix = "🚀 <b>PUBLICAT A INSTAGRAM & FACEBOOK</b>\n\n" if is_published else "🧪 <b>PREVIEW (MODE PROVA)</b>\n\n"
    
    max_len = 1024 - len(prefix) - 5
    safe_caption = caption if len(caption) <= max_len else caption[:max_len] + "..."
    full_caption = prefix + html.escape(safe_caption)

    media = []
    files = {}
    for i, path in enumerate(image_paths):
        file_key = f"photo_{i}"
        item = {"type": "photo", "media": f"attach://{file_key}"}
        if i == 0:
            item["caption"] = full_caption
            item["parse_mode"] = "HTML"
        media.append(item)
        files[file_key] = open(path, "rb")

    try:
        payload = {"chat_id": CHAT_ID, "media": json.dumps(media)}
        res = requests.post(url, data=payload, files=files, timeout=35)
        res.raise_for_status()
        print("📱 Carrousel enviat correctament a Telegram!")
    finally:
        for f in files.values():
            f.close()


# --- PROCÉS PRINCIPAL ---
def main():
    ensure_workspace()

    print(f"📖 Llegint la següent notícia de {CSV_FILE}...")
    news_item, all_rows = get_next_pending_news()

    if not news_item:
        print("⚠️ No hi ha cap notícia pendent al CSV!")
        return

    news_id = news_item["id"]
    h1, q1 = news_item["headline_1"], news_item["query_1"]
    h2, q2 = news_item["headline_2"], news_item["query_2"]
    h3, q3 = news_item["headline_3"], news_item["query_3"]
    caption = news_item["caption"]

    print(f"\n🎬 Processant Notícia #{news_id}")

    # 1. Descarregar imatges web reals via Serper
    temp_img1 = os.path.join(IMAGES_DIR, f"temp_{news_id}_1.jpg")
    temp_img2 = os.path.join(IMAGES_DIR, f"temp_{news_id}_2.jpg")
    temp_img3 = os.path.join(IMAGES_DIR, f"temp_{news_id}_3.jpg")

    search_and_download_image(q1, temp_img1)
    search_and_download_image(q2, temp_img2)
    search_and_download_image(q3, temp_img3)

    # 2. Slide 4 (Outro amb background_news.png)
    temp_img4 = OUTRO_BG_PATH
    if not os.path.exists(temp_img4):
        temp_img4 = os.path.join(IMAGES_DIR, "temp_outro_fallback.jpg")
        Image.new("RGB", (1080, 1350), color=(18, 18, 22)).save(temp_img4)

    # Text oficial de tancament amb BREAKING NEWS
    h4 = "FOLLOW **@HOMER.NEWS** FOR MORE UNFILTERED **BREAKING NEWS**"

    # 3. Renderitzar les 4 diapositives
    out_slide1 = os.path.join(IMAGES_DIR, f"news_{news_id}_s1.jpg")
    out_slide2 = os.path.join(IMAGES_DIR, f"news_{news_id}_s2.jpg")
    out_slide3 = os.path.join(IMAGES_DIR, f"news_{news_id}_s3.jpg")
    out_slide4 = os.path.join(IMAGES_DIR, f"news_{news_id}_s4.jpg")

    # Slides 1, 2 i 3: Disseny periodístic amb línies, degradat i logo petit
    render_slide(temp_img1, h1, "SWIPE FOR FULL STORY", out_slide1, has_arrow=True)
    render_slide(temp_img2, h2, "SWIPE", out_slide2, has_arrow=True)
    render_slide(temp_img3, h3, "READ THE CAPTION", out_slide3, has_arrow=False)

    # Slide 4: Disseny net centrat estil Canva (logo gran + text amb perfilat negre)
    render_outro_slide(temp_img4, h4, "HOMER.NEWS", out_slide4)

    carousel_paths = [out_slide1, out_slide2, out_slide3, out_slide4]

    for p in [temp_img1, temp_img2, temp_img3]:
        if os.path.exists(p): os.remove(p)

    if MODE_PROVA:
        print("\n🧪 MODE_PROVA = True. Enviant preview a Telegram...")
        send_telegram_carousel(carousel_paths, caption, is_published=False)
    else:
        print("\n🚀 MODE_PROVA = False. Pujant carrousel i publicant...")
        mark_news_as_done(news_id, all_rows)
        public_urls = push_carousel_to_github(carousel_paths, news_id)

        # Publicació a Instagram
        publish_carousel_to_buffer(public_urls, caption, BUFFER_CHANNEL_ID, platform="instagram")
        # Publicació a Facebook
        publish_carousel_to_buffer(public_urls, caption, BUFFER_FB_CHANNEL_ID, platform="facebook")
        
        # Enviar còpia a Telegram
        send_telegram_carousel(carousel_paths, caption, is_published=True)


if __name__ == "__main__":
    main()
