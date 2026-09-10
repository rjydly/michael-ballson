import os
import re
import json
import html
import time
import subprocess
import requests
from PIL import Image, ImageDraw, ImageFont
from google import genai
from google.genai import types

# ==============================================================================
# CONFIGURACIÓ PRINCIPAL
# ==============================================================================
# True  -> Només genera la imatge i l'envia a Telegram (sense publicar a xarxes).
# False -> Publica a Instagram via Buffer I TAMBÉ envia còpia a Telegram.
MODE_PROVA = False

ACCOUNT_NAME = "@homer.news"
IMAGES_DIR = "images"
OUTPUT_IMAGE = os.path.join(IMAGES_DIR, "news_post.jpg")
LOGO_PATH = os.path.join("assets", "logo.png")
FONT_PATH = os.path.join("assets", "Anton-Regular.ttf")

# Variables d'entorn
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
BUFFER_ACCESS_TOKEN = os.getenv("BUFFER_ACCESS_TOKEN")
BUFFER_CHANNEL_ID = os.getenv("BUFFER_CHANNEL_ID")
GITHUB_REPOSITORY = os.getenv("GITHUB_REPOSITORY")


def ensure_workspace():
    """Assegura les carpetes de treball necessàries."""
    if not os.path.exists("assets"):
        os.makedirs("assets")
    if not os.path.exists(IMAGES_DIR):
        os.makedirs(IMAGES_DIR)


def ensure_font_exists():
    """Assegura que la font Anton existeixi; si no, la descarrega."""
    ensure_workspace()
    if not os.path.exists(FONT_PATH):
        print("⬇️ Descarregant font Anton de Google Fonts...")
        font_url = "https://raw.githubusercontent.com/google/fonts/main/ofl/anton/Anton-Regular.ttf"
        res = requests.get(font_url, timeout=15)
        with open(FONT_PATH, "wb") as f:
            f.write(res.content)
    return FONT_PATH


def generate_satirical_news():
    client = genai.Client(api_key=GEMINI_API_KEY)
    
    prompt = """
    You are the Editor-in-Chief of a viral satirical news outlet (in the style of The Onion and Reductress).
    
    TARGET AUDIENCE & CULTURAL CONTEXT:
    - Primary Audience: Young adults, Millennials, and Gen Z residing in EUROPE and NORTH AMERICA (US, UK, Canada, and EU).
    - Cultural Touchpoints: Shared Western modern lifestyle—remote work dilemmas, budget airline luggage nightmares, Sunday evening anxiety, flatmate/roommate dynamics, expensive specialty coffee, self-checkout machine arguments, subscription fatigue (paying for 5 streaming apps to watch nothing), and modern dating culture.
    - Avoid ultra-niche local political references. Focus on universal human absurdities that anyone living in London, New York, Berlin, Toronto, Paris, or Barcelona instantly relates to.
    
    YOUR COMIC FORMULA:
    Take an insanely petty, embarrassing, or hyper-relatable everyday human struggle and report on it with the DEADPAN SERIOUSNESS of breaking Pulitzer-winning news.
    
    STUDY THESE EXCELLENT HEADLINE EXAMPLES:
    - Example 1: "**MAN** ACCIDENTALLY CLOSES 48 OPEN BROWSER TABS HE WAS '**DEFINITELY GOING TO READ** LATER'"
    - Example 2: "**WOMAN** BUYS $8 ICED MATCHA LATTE TO MOTIVATE HERSELF TO WORK FOR **EXACTLY 6 MINUTES**"
    - Example 3: "**SCIENTISTS CONFIRM** 90% OF YOUR TIREDNESS WOULD DISAPPEAR IF YOU JUST **DRANK SOME DAMN WATER**"
    - Example 4: "**LOCAL MAN** REWARDS HIMSELF FOR COMPLETING ONE TINY TASK WITH A **4-HOUR COMA NAP**"
    - Example 5: "**TRAVELER** SUFFERS SEVERE ANXIETY WATCHING FLIGHT ATTENDANT INSPECT **SLIGHTLY BULGING BACKPACK**"
    - Example 6: "**COUPLE** REACHES DANGEROUS LEVEL OF COMFORT WHERE THEY ONLY COMMUNICATE IN **UNINTELLIGIBLE GRUNTS**"
    
    RULES:
    1. Everything MUST be written in 100% ENGLISH.
    2. Headline must be punchy (10 to 14 words max).
    3. Put double asterisks **around 2 to 3 punchy keywords** that should be colored bright yellow.
    4. The caption MUST expand on the absurd premise with 2 hilarious, deadpan journalistic paragraphs.
    5. At the very end of the caption, ALWAYS include an explicit, witty disclaimer stating that this is SATIRE (e.g. "(Disclaimer: This is satire. Please do not cite us in court.)" or "(Note: This is satire / fake news, but painfully real.)") followed by 4-5 relevant hashtags.
    
    Respond ONLY with valid JSON with these exact keys:
    - "headline": Uppercase headline string with **highlighted** words.
    - "search_query": Simple English photo search query for Pexels representing realistic everyday humans/situations (e.g. "stressed woman kitchen counter", "tired man in bed phone", "couple sitting sofa distant", "confused passenger airport gate").
    - "caption": Full caption text including the satirical joke breakdown, the satire disclaimer, and hashtags.
    """

    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        try:
            print(f"🤖 Connectant amb Gemini (intent {attempt}/{max_attempts})...")
            res = client.models.generate_content(
                model="gemini-3.6-flash",
                contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json")
            )
            data = json.loads(res.text)
            return data["headline"], data["search_query"], data["caption"]
        except Exception as e:
            print(f"⚠️ Error amb Gemini a l'intent {attempt}: {e}")
            if attempt < max_attempts:
                print("⏳ Esperant 60 segons abans de reintentar...")
                time.sleep(60)
            else:
                print("🛑 S'han esgotat els 3 intents amb Gemini. S'abandona el procés.")
                raise e


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

    # 1. Carregar i retallar imatge a proporció 4:5
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

    # 2. Mides i coordenades
    line_h = int(font_size * 1.12)
    total_text_h = len(lines) * line_h
    
    bottom_margin = 120
    text_start_y = CANVAS_H - bottom_margin - total_text_h
    separator_y = text_start_y - 100

    # 3. Degradat fosc
    gradient = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 0))
    draw_g = ImageDraw.Draw(gradient)

    gradient_top = int(CANVAS_H * 0.28)
    for y in range(gradient_top, CANVAS_H):
        progress = (y - gradient_top) / (CANVAS_H - gradient_top)
        alpha = int(255 * (progress ** 1.15))
        draw_g.line([(0, y), (CANVAS_W, y)], fill=(0, 0, 0, min(255, alpha)))

    final_img = Image.alpha_composite(img, gradient).convert("RGBA")
    draw = ImageDraw.Draw(final_img)

    # 4. Línia amb el logo
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

    # 5. Titular
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

    # 6. Peu de pàgina
    footer_text = "READ THE CAPTION"
    fb_bbox = draw.textbbox((0, 0), footer_text, font=font_footer)
    fb_w = fb_bbox[2] - fb_bbox[0]
    draw.text(((CANVAS_W - fb_w) // 2, CANVAS_H - 55), footer_text, font=font_footer, fill=(160, 160, 160))

    final_output = final_img.convert("RGB")
    final_output.save(OUTPUT_IMAGE, quality=95)

    if os.path.exists(stock_path):
        os.remove(stock_path)
    return OUTPUT_IMAGE


def send_preview_to_telegram(image_path, caption, is_published=False):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("⚠️ No s'han configurat TELEGRAM_TOKEN o CHAT_ID.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    caption_escaped = html.escape(caption)
    
    prefix = "🚀 <b>PUBLICAT A INSTAGRAM (@homer.news)</b>" if is_published else "🧪 <b>PREVIEW (MODE PROVA)</b>"
    caption_text = f"{prefix}\n\n{caption_escaped}"

    if len(caption_text) > 1024:
        caption_text = caption_text[:1020] + "..."

    with open(image_path, "rb") as photo:
        payload = {
            "chat_id": CHAT_ID,
            "caption": caption_text,
            "parse_mode": "HTML"
        }
        files = {"photo": photo}
        res = requests.post(url, data=payload, files=files, timeout=30)
        res.raise_for_status()

    print("📱 Notificació enviada a Telegram!")


def push_image_to_github(filepath):
    """Fa push de la imatge generada al repositori per tenir una URL pública per a Buffer."""
    print("🌐 Pujant imatge a GitHub per a l'enllaç públic...")
    subprocess.run(["git", "config", "--local", "user.email", "bot@github.com"], check=True)
    subprocess.run(["git", "config", "--local", "user.name", "NewsBot"], check=True)
    
    subprocess.run(["git", "add", "-f", filepath], check=True)
    commit_res = subprocess.run(["git", "commit", "-m", "Nova imatge de notícia [skip ci]"])
    if commit_res.returncode == 0:
        subprocess.run(["git", "push"], check=True)
        time.sleep(5)
    
    filename = os.path.basename(filepath)
    raw_url = f"https://raw.githubusercontent.com/{GITHUB_REPOSITORY}/main/{IMAGES_DIR}/{filename}"
    print(f"🔗 URL pública de la imatge: {raw_url}")
    return raw_url


def publish_image_to_buffer(image_public_url, caption):
    """Envia la imatge a Instagram Feed a través de la GraphQL API de Buffer."""
    print("🚀 Publicant la notícia a Instagram via Buffer...")
    query = """
    mutation CreatePost($input: CreatePostInput!) {
      createPost(input: $input) {
        ... on PostActionSuccess { post { id } }
        ... on MutationError { message }
      }
    }
    """
    # Fix: Buffer exigeix shouldShareToFeed: True també a les imatges de tipus 'post'
    variables = {
        "input": {
            "text": caption,
            "channelId": BUFFER_CHANNEL_ID,
            "schedulingType": "automatic",
            "mode": "shareNow",
            "assets": [
                {
                    "image": {
                        "url": image_public_url
                    }
                }
            ],
            "metadata": {
                "instagram": {
                    "type": "post",
                    "shouldShareToFeed": True
                }
            }
        }
    }
    headers = {
        "Authorization": f"Bearer {BUFFER_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    res = requests.post("https://api.buffer.com", json={"query": query, "variables": variables}, headers=headers).json()
    
    if "errors" in res:
        raise Exception(f"Error GraphQL Buffer: {res['errors']}")
    post_data = res.get("data", {}).get("createPost", {})
    if "message" in post_data:
        raise Exception(f"Error Buffer: {post_data['message']}")

    print("🎉 Notícia publicada amb èxit a Instagram!")


def main():
    ensure_workspace()

    print("1. Generant titular per a audiència Europa / Nord-amèrica amb Gemini...")
    headline, keyword, caption = generate_satirical_news()
    print(f"👉 Headline: {headline}")
    print(f"👉 Keyword Pexels: {keyword}")

    print("2. Descarregant foto d'estoc de Pexels...")
    stock_img = download_pexels_image(keyword)

    print("3. Processant disseny...")
    output_img = render_news_image(stock_img, headline)

    if MODE_PROVA:
        print("\n🧪 MODE_PROVA = True. No es publica a Instagram, només s'envia a Telegram.")
        send_preview_to_telegram(output_img, caption, is_published=False)
    else:
        print("\n🚀 MODE_PROVA = False. Iniciant publicació a Instagram...")
        raw_url = push_image_to_github(output_img)
        publish_image_to_buffer(raw_url, caption)
        send_preview_to_telegram(output_img, caption, is_published=True)


if __name__ == "__main__":
    main()
