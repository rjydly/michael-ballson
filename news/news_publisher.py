import os
import re
import csv
import html
import time
import subprocess
import requests
from PIL import Image, ImageDraw, ImageFont
from duckduckgo_search import DDGS

# ==============================================================================
# CONFIGURACIÓ PRINCIPAL
# ==============================================================================
MODE_PROVA = False  # False = Publica a Instagram/Facebook via Buffer i marca 'done'

ACCOUNT_NAME = "@homer.news"
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NEWS_DIR = os.path.join(BASE_DIR, "news")
CSV_FILE = os.path.join(NEWS_DIR, "news_database.csv")
IMAGES_DIR = os.path.join(BASE_DIR, "images")
ASSETS_DIR = os.path.join(BASE_DIR, "assets")

LOGO_PATH = os.path.join(ASSETS_DIR, "logo.png")
FONT_PATH = os.path.join(ASSETS_DIR, "Anton-Regular.ttf")
OUTRO_BG_PATH = os.path.join(ASSETS_DIR, "background_news.png")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
BUFFER_ACCESS_TOKEN = os.getenv("BUFFER_ACCESS_TOKEN")
BUFFER_CHANNEL_ID = os.getenv("BUFFER_CHANNEL_ID")
BUFFER_FB_CHANNEL_ID = os.getenv("BUFFER_FB_CHANNEL_ID")
GITHUB_REPOSITORY = os.getenv("GITHUB_REPOSITORY")


def ensure_workspace():
    os.makedirs(ASSETS_DIR, exist_ok=True)
    os.makedirs(IMAGES_DIR, exist_ok=True)
    os.makedirs(NEWS_DIR, exist_ok=True)


def ensure_font_exists():
    ensure_workspace()
    if not os.path.exists(FONT_PATH):
        print("⬇️ Descarregant font Anton de Google Fonts...")
        font_url = "https://raw.githubusercontent.com/google/fonts/main/ofl/anton/Anton-Regular.ttf"
        res = requests.get(font_url, timeout=15)
        with open(FONT_PATH, "wb") as f:
            f.write(res.content)
    return FONT_PATH


def get_next_pending_news():
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
    for r in rows:
        if str(r["id"]) == str(news_id):
            r["status"] = "done"
            break

    fieldnames = ["id", "headline_1", "query_1", "headline_2", "query_2", "headline_3", "query_3", "caption", "status"]
    with open(CSV_FILE, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(rows)


# --- DESCÀRREGA D'IMATGES WEB (DUCKDUCKGO) ---
def search_and_download_image(query, target_filename):
    print(f"🔍 Cercant imatge a internet per: '{query}'...")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    }

    image_url = None
    try:
        with DDGS() as ddgs:
            results = list(ddgs.images(query, max_results=5))
            if results:
                image_url = results[0].get("image")
    except Exception as e:
        print(f"⚠️ Avís cercant a DuckDuckGo: {e}")

    if not image_url:
        print(f"⚠️ Cerca fallida per '{query}'. Fent cerca de seguretat...")
        try:
            with DDGS() as ddgs:
                results = list(ddgs.images(query.split()[0] + " news viral", max_results=5))
                if results:
                    image_url = results[0].get("image")
        except Exception:
            pass

    if image_url:
        try:
            res = requests.get(image_url, headers=headers, timeout=20)
            if res.status_code == 200:
                with open(target_filename, "wb") as f:
                    f.write(res.content)
                # Validar que és una imatge vàlida
                with Image.open(target_filename) as test_img:
                    test_img.verify()
                return target_filename
        except Exception as e:
            print(f"⚠️ Error descarregant imatge de {image_url}: {e}")

    # Imatge neutra de reserva si la descàrrega web falla completament
    print("ℹ️ Creant fons fosc de reserva...")
    fallback_img = Image.new("RGB", (1080, 1350), color=(25, 25, 30))
    fallback_img.save(target_filename)
    return target_filename


# --- MOTOR GRÀFIC PILLOW ---
def parse_headline_words(headline_text):
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


def render_slide(source_image_path, headline_raw, footer_text, output_path):
    CANVAS_W, CANVAS_H = 1080, 1350
    font_file = ensure_font_exists()

    font_size = 74
    font_headline = ImageFont.truetype(font_file, font_size)
    font_footer = ImageFont.truetype(font_file, 26)
    font_fallback_logo = ImageFont.truetype(font_file, 44)

    # 1. Carregar i retallar imatge 4:5
    img = Image.open(source_image_path).convert("RGBA")
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

    # 4. Text Anton amb ressaltat groc
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

    # 5. Peu de pàgina
    fb_bbox = draw.textbbox((0, 0), footer_text, font=font_footer)
    fb_w = fb_bbox[2] - fb_bbox[0]
    draw.text(((CANVAS_W - fb_w) // 2, CANVAS_H - 55), footer_text, font=font_footer, fill=(170, 170, 170))

    final_img.convert("RGB").save(output_path, quality=95)
    return output_path


# --- GIT I BUFFER CARROUSEL ---
def push_carousel_to_github(image_paths, news_id):
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
    if not channel_id:
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
    metadata_payload = (
        {"instagram": {"type": "carousel", "shouldShareToFeed": True}}
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
        raise Exception(f"Error Buffer {platform}: {res['errors']}")
    print(f"✅ Carrousel publicat amb èxit a {platform.capitalize()}!")


def send_telegram_carousel(image_paths, caption, is_published=False):
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
        import json
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
        print("⚠️ No hi ha cap notícia pendent al CSV! Executa generate_batch.py.")
        if TELEGRAM_TOKEN and CHAT_ID:
            requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={
                "chat_id": CHAT_ID,
                "text": "⚠️ <b>ALERTA:</b> La cua de notícies carrousel a <code>news_database.csv</code> s'ha buidat!"
            }, timeout=10)
        return

    news_id = news_item["id"]
    h1, q1 = news_item["headline_1"], news_item["query_1"]
    h2, q2 = news_item["headline_2"], news_item["query_2"]
    h3, q3 = news_item["headline_3"], news_item["query_3"]
    caption = news_item["caption"]

    print(f"\n🎬 Processant Notícia #{news_id}")
    print(f"👉 Slide 1: {h1}")
    print(f"👉 Slide 2: {h2}")
    print(f"👉 Slide 3: {h3}")

    # 1. Descarregar imatges web per a les slides 1, 2 i 3
    temp_img1 = os.path.join(IMAGES_DIR, f"temp_{news_id}_1.jpg")
    temp_img2 = os.path.join(IMAGES_DIR, f"temp_{news_id}_2.jpg")
    temp_img3 = os.path.join(IMAGES_DIR, f"temp_{news_id}_3.jpg")

    search_and_download_image(q1, temp_img1)
    search_and_download_image(q2, temp_img2)
    search_and_download_image(q3, temp_img3)

    # 2. Slide 4 (Outro amb background_news.png)
    temp_img4 = OUTRO_BG_PATH
    if not os.path.exists(temp_img4):
        print("ℹ️ 'assets/background_news.png' no trobat. Fent servir fons fosc d'estudi...")
        temp_img4 = os.path.join(IMAGES_DIR, "temp_outro_fallback.jpg")
        Image.new("RGB", (1080, 1350), color=(18, 18, 22)).save(temp_img4)

    h4 = "FOLLOW **@HOMER.NEWS** FOR MORE UNFILTERED **BREAKING SATIRE**"

    # 3. Renderitzar les 4 diapositives
    out_slide1 = os.path.join(IMAGES_DIR, f"news_{news_id}_s1.jpg")
    out_slide2 = os.path.join(IMAGES_DIR, f"news_{news_id}_s2.jpg")
    out_slide3 = os.path.join(IMAGES_DIR, f"news_{news_id}_s3.jpg")
    out_slide4 = os.path.join(IMAGES_DIR, f"news_{news_id}_s4.jpg")

    render_slide(temp_img1, h1, "SWIPE FOR FULL STORY ➔", out_slide1)
    render_slide(temp_img2, h2, "SWIPE ➔", out_slide2)
    render_slide(temp_img3, h3, "READ THE CAPTION", out_slide3)
    render_slide(temp_img4, h4, "HOMER.NEWS", out_slide4)

    carousel_paths = [out_slide1, out_slide2, out_slide3, out_slide4]

    # Netejar temporals de descàrrega
    for p in [temp_img1, temp_img2, temp_img3]:
        if os.path.exists(p): os.remove(p)

    if MODE_PROVA:
        print("\n🧪 MODE_PROVA = True. Enviant preview del carrousel a Telegram...")
        send_telegram_carousel(carousel_paths, caption, is_published=False)
    else:
        print("\n🚀 MODE_PROVA = False. Pujant carrousel i publicant...")
        mark_news_as_done(news_id, all_rows)
        public_urls = push_carousel_to_github(carousel_paths, news_id)

        publish_carousel_to_buffer(public_urls, caption, BUFFER_CHANNEL_ID, platform="instagram")
        publish_carousel_to_buffer(public_urls, caption, BUFFER_FB_CHANNEL_ID, platform="facebook")
        send_telegram_carousel(carousel_paths, caption, is_published=True)


if __name__ == "__main__":
    main()
