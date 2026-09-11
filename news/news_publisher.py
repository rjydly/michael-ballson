import os
import re
import csv
import html
import time
import subprocess
import requests
from PIL import Image, ImageDraw, ImageFont

# ==============================================================================
# CONFIGURACIÓ PRINCIPAL
# ==============================================================================
MODE_PROVA = False  # False = Publica a Instagram + Facebook i marca 'done' al CSV

ACCOUNT_NAME = "@homer.news"
NEWS_DIR = "news"
CSV_FILE = os.path.join(NEWS_DIR, "news_database.csv")
IMAGES_DIR = "images"
OUTPUT_IMAGE = os.path.join(IMAGES_DIR, "news_post.jpg")
LOGO_PATH = os.path.join("assets", "logo.png")
FONT_PATH = os.path.join("assets", "Anton-Regular.ttf")

# Secrets
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
BUFFER_ACCESS_TOKEN = os.getenv("BUFFER_ACCESS_TOKEN")
BUFFER_CHANNEL_ID = os.getenv("BUFFER_CHANNEL_ID")          # Instagram
BUFFER_FB_CHANNEL_ID = os.getenv("BUFFER_FB_CHANNEL_ID")    # Facebook Page
GITHUB_REPOSITORY = os.getenv("GITHUB_REPOSITORY")


def ensure_workspace():
    if not os.path.exists("assets"):
        os.makedirs("assets")
    if not os.path.exists(IMAGES_DIR):
        os.makedirs(IMAGES_DIR)
    if not os.path.exists(NEWS_DIR):
        os.makedirs(NEWS_DIR)


def ensure_font_exists():
    ensure_workspace()
    if not os.path.exists(FONT_PATH):
        print("⬇️ Descarregant font Anton de Google Fonts...")
        font_url = "https://raw.githubusercontent.com/google/fonts/main/ofl/anton/Anton-Regular.ttf"
        res = requests.get(font_url, timeout=15)
        with open(FONT_PATH, "wb") as f:
            f.write(res.content)
    return FONT_PATH


# --- GESTIÓ DEL CSV ---
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
        if r["id"] == str(news_id):
            r["status"] = "done"
            break

    with open(CSV_FILE, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "headline", "search_query", "caption", "status"], quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(rows)


# --- PROCESSAMENT DE FOTO I DISSENY ---
def download_pexels_image(query):
    url = f"https://api.pexels.com/v1/search?query={query}&per_page=1&orientation=portrait"
    headers = {"Authorization": PEXELS_API_KEY}
    res = requests.get(url, headers=headers).json()

    if res.get("photos"):
        img_url = res["photos"][0]["src"]["large2x"]
        img_data = requests.get(img_url).content
        temp_path = "temp_stock.jpg"
        with open(temp_path, "wb") as f:
            f.write(img_data)
        return temp_path
    raise Exception(f"No s'ha trobat cap foto a Pexels per: {query}")


def parse_headline_words(headline_text):
    tokens = re.split(r'(\*\*.*?\*\*)', headline_text)
    parsed = []
    for token in tokens:
        if token.startswith("**") and token.endswith("**"):
            words = token[2:-2].strip().split()
            for w in words:
                if w:
                    parsed.append((w.upper(), True))
        else:
            words = token.strip().split()
            for w in words:
                if w:
                    parsed.append((w.upper(), False))
    return parsed


def wrap_words_to_lines(parsed_words, font, max_width, draw):
    space_w = draw.textbbox((0, 0), " ", font=font)[2]
    lines = []
    current_line = []
    current_w = 0

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


def render_news_image(stock_path, headline_raw):
    CANVAS_W, CANVAS_H = 1080, 1350
    font_file = ensure_font_exists()

    font_size = 76
    font_headline = ImageFont.truetype(font_file, font_size)
    font_footer = ImageFont.truetype(font_file, 26)
    font_fallback_logo = ImageFont.truetype(font_file, 44)

    img = Image.open(stock_path).convert("RGBA")
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
    separator_y = text_start_y - 100

    gradient = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 0))
    draw_g = ImageDraw.Draw(gradient)

    gradient_top = int(CANVAS_H * 0.28)
    for y in range(gradient_top, CANVAS_H):
        progress = (y - gradient_top) / (CANVAS_H - gradient_top)
        alpha = int(255 * (progress ** 1.15))
        draw_g.line([(0, y), (CANVAS_W, y)], fill=(0, 0, 0, min(255, alpha)))

    final_img = Image.alpha_composite(img, gradient).convert("RGBA")
    draw = ImageDraw.Draw(final_img)

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
        txt_w = bbox[2] - bbox[0]
        txt_h = bbox[3] - bbox[1]
        txt_x = (CANVAS_W - txt_w) // 2
        txt_y = separator_y - (txt_h // 2) - 4

        draw.line([(side_margin, separator_y), (txt_x - 25, separator_y)], fill=(210, 210, 210, 220), width=3)
        draw.line([(txt_x + txt_w + 25, separator_y), (CANVAS_W - side_margin, separator_y)], fill=(210, 210, 210, 220), width=3)
        draw.text((txt_x, txt_y), fallback_txt, font=font_fallback_logo, fill=(230, 230, 230))

    space_w = draw.textbbox((0, 0), " ", font=font_headline)[2]
    current_y = text_start_y
    COLOR_WHITE = (255, 255, 255)
    COLOR_YELLOW = (255, 230, 0)

    for line in lines:
        line_w = sum(w for _, _, w in line) + (len(line) - 1) * space_w
        start_x = (CANVAS_W - line_w) // 2

        cur_x = start_x
        for word, is_highlight, w in line:
            color = COLOR_YELLOW if is_highlight else COLOR_WHITE
            draw.text((cur_x, current_y), word, font=font_headline, fill=color)
            cur_x += w + space_w

        current_y += line_h

    footer_text = "READ THE CAPTION"
    fb_bbox = draw.textbbox((0, 0), footer_text, font=font_footer)
    fb_w = fb_bbox[2] - fb_bbox[0]
    draw.text(((CANVAS_W - fb_w) // 2, CANVAS_H - 55), footer_text, font=font_footer, fill=(160, 160, 160))

    final_output = final_img.convert("RGB")
    final_output.save(OUTPUT_IMAGE, quality=95)

    if os.path.exists(stock_path):
        os.remove(stock_path)
    return OUTPUT_IMAGE


# --- TELEGRAM I BUFFER ---
def send_telegram(image_path, caption, headline, is_published=False):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    caption_escaped = html.escape(caption)
    prefix = "🚀 <b>PUBLICAT A INSTAGRAM & FACEBOOK</b>" if is_published else "🧪 <b>PREVIEW (MODE PROVA)</b>"
    caption_text = f"{prefix}\n\n{caption_escaped}"

    if len(caption_text) > 1024:
        caption_text = caption_text[:1020] + "..."

    with open(image_path, "rb") as photo:
        payload = {"chat_id": CHAT_ID, "caption": caption_text, "parse_mode": "HTML"}
        files = {"photo": photo}
        res = requests.post(url, data=payload, files=files, timeout=30)
        res.raise_for_status()


def push_to_github(filepath, news_id):
    """Puja la imatge I el CSV actualitzat a GitHub."""
    print("🌐 Sincronitzant imatge i CSV amb GitHub...")
    subprocess.run(["git", "config", "--local", "user.email", "bot@github.com"], check=True)
    subprocess.run(["git", "config", "--local", "user.name", "NewsBot"], check=True)
    
    subprocess.run(["git", "add", "-f", filepath], check=True)
    subprocess.run(["git", "add", CSV_FILE], check=True)
    commit_res = subprocess.run(["git", "commit", "-m", f"Publicada notícia #{news_id} [skip ci]"])
    if commit_res.returncode == 0:
        subprocess.run(["git", "push"], check=True)
        time.sleep(5)
    
    filename = os.path.basename(filepath)
    return f"https://raw.githubusercontent.com/{GITHUB_REPOSITORY}/main/{IMAGES_DIR}/{filename}"


def publish_to_instagram(image_public_url, caption):
    if not BUFFER_CHANNEL_ID:
        return
    print("🚀 Publicant a Instagram...")
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
            "assets": [{"image": {"url": image_public_url}}],
            "metadata": {"instagram": {"type": "post", "shouldShareToFeed": True}}
        }
    }
    headers = {"Authorization": f"Bearer {BUFFER_ACCESS_TOKEN}", "Content-Type": "application/json"}
    res = requests.post("https://api.buffer.com", json={"query": query, "variables": variables}, headers=headers).json()
    if "errors" in res: raise Exception(f"Error Buffer Instagram: {res['errors']}")
    print("✅ Publicat a Instagram!")


def publish_to_facebook(image_public_url, caption):
    if not BUFFER_FB_CHANNEL_ID:
        return
    print("🚀 Publicant a Facebook...")
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
            "channelId": BUFFER_FB_CHANNEL_ID,
            "schedulingType": "automatic",
            "mode": "shareNow",
            "assets": [{"image": {"url": image_public_url}}],
            "metadata": {"facebook": {"type": "post"}}
        }
    }
    headers = {"Authorization": f"Bearer {BUFFER_ACCESS_TOKEN}", "Content-Type": "application/json"}
    res = requests.post("https://api.buffer.com", json={"query": query, "variables": variables}, headers=headers).json()
    if "errors" in res: raise Exception(f"Error Buffer Facebook: {res['errors']}")
    print("✅ Publicat a Facebook!")


def main():
    ensure_workspace()

    print(f"📖 Llegint la següent notícia de {CSV_FILE}...")
    news_item, all_rows = get_next_pending_news()

    if not news_item:
        print("⚠️ No hi ha cap notícia pendent al CSV! Executa generate_batch.py per afegir-ne més.")
        if TELEGRAM_TOKEN and CHAT_ID:
            requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={
                "chat_id": CHAT_ID,
                "text": "⚠️ <b>ALERTA:</b> La cua de notícies de <code>news_database.csv</code> s'ha buidat! Afegeix-ne més."
            })
        return

    news_id = news_item["id"]
    headline = news_item["headline"]
    keyword = news_item["search_query"]
    caption = news_item["caption"]

    print(f"👉 Notícia #{news_id}: {headline}")
    print(f"👉 Cerca Pexels: {keyword}")

    print("📸 Descarregant foto de Pexels...")
    stock_img = download_pexels_image(keyword)

    print("🎨 Renderitzant disseny...")
    output_img = render_news_image(stock_img, headline)

    if MODE_PROVA:
        print("\n🧪 MODE_PROVA = True. Enviant només preview a Telegram (no es marca com a 'done').")
        send_telegram(output_img, caption, headline, is_published=False)
    else:
        print("\n🚀 MODE_PROVA = False. Publicant a xarxes...")
        mark_news_as_done(news_id, all_rows)
        raw_url = push_to_github(output_img, news_id)

        publish_to_instagram(raw_url, caption)
        publish_to_facebook(raw_url, caption)

        send_telegram(output_img, caption, headline, is_published=True)


if __name__ == "__main__":
    main()
