import os
import json
import html
import requests
import textwrap
from PIL import Image, ImageDraw, ImageFont
from google import genai
from google.genai import types

# --- CONFIGURACIÓ ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

BRAND_NAME = "HOMER NEWS"
OUTPUT_IMAGE = "preview_news.jpg"


def generate_satirical_news():
    client = genai.Client(api_key=GEMINI_API_KEY)
    prompt = """
    Ets un guionista d'un diari satíric d'humor absurd (estil El Mundo Today / The Onion) centrat en intel·ligència artificial, tecnologia i societat digital.
    
    Genera una notícia satírica breu. Respon ÚNICAMENT en format JSON amb aquestes claus:
    - "titular": Titular sensacionalista i absurd en majúscules (màxim 12 paraules).
    - "cerca_imatge": Paraules clau en anglès senzilles per cercar una foto realista a Pexels (ex: "stressed office worker", "confused robot", "laptop on fire", "suit handshake").
    - "caption": Text complet per al peu de foto d'Instagram explicant la broma breument amb 4-5 hashtags.
    """

    res = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json")
    )
    data = json.loads(res.text)
    return data["titular"], data["cerca_imatge"], data["caption"]


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


def render_news_image(stock_path, titular, brand):
    CANVAS_W, CANVAS_H = 1080, 1350
    img = Image.open(stock_path).convert("RGBA")

    # Escalar i retallar a proporció 4:5
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

    # Degradat fosc a la part inferior
    gradient = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 0))
    draw_g = ImageDraw.Draw(gradient)
    start_y = int(CANVAS_H * 0.42)
    for y in range(start_y, CANVAS_H):
        alpha = int(255 * ((y - start_y) / (CANVAS_H - start_y)))
        draw_g.line([(0, y), (CANVAS_W, y)], fill=(0, 0, 0, alpha))

    final_img = Image.alpha_composite(img, gradient).convert("RGB")
    draw = ImageDraw.Draw(final_img)

    # Carregar fonts
    font_path = "assets/BebasNeue-Regular.ttf"
    if os.path.exists(font_path):
        font_headline = ImageFont.truetype(font_path, 76)
        font_brand = ImageFont.truetype(font_path, 30)
    else:
        font_headline = ImageFont.load_default()
        font_brand = ImageFont.load_default()

    # Divisió de marca
    brand_line = f"—— {brand} ——"
    bbox_b = draw.textbbox((0, 0), brand_line, font=font_brand)
    bw = bbox_b[2] - bbox_b[0]
    brand_y = CANVAS_H - 480
    draw.text(((CANVAS_W - bw) / 2, brand_y), brand_line, font=font_brand, fill=(210, 210, 210))

    # Titular dividit en línies
    lines = textwrap.wrap(titular.upper(), width=22)
    text_y = brand_y + 55
    for line in lines:
        bbox_l = draw.textbbox((0, 0), line, font=font_headline)
        lw = bbox_l[2] - bbox_l[0]
        lh = bbox_l[3] - bbox_l[1]
        draw.text(((CANVAS_W - lw) / 2, text_y), line, font=font_headline, fill=(255, 255, 255))
        text_y += lh + 18

    final_img.save(OUTPUT_IMAGE, quality=95)

    if os.path.exists(stock_path):
        os.remove(stock_path)
    return OUTPUT_IMAGE


def send_preview_to_telegram(image_path, caption):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        raise Exception("Falten les variables TELEGRAM_TOKEN o CHAT_ID.")

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    caption_escaped = html.escape(caption)
    caption_text = f"📰 <b>NOVA NOTÍCIA GENERADA (PREVIEW)</b>\n\n{caption_escaped}"
    
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

    print("📱 Disseny enviat correctament a Telegram!")


def main():
    print("1. Demanant idea satírica a Gemini...")
    titular, keyword, caption = generate_satirical_news()
    print(f"👉 Titular: {titular}")
    print(f"👉 Cerca Pexels: {keyword}")

    print("2. Descarregant foto d'estoc...")
    stock_img = download_pexels_image(keyword)

    print("3. Generant disseny...")
    output_img = render_news_image(stock_img, titular, BRAND_NAME)

    print("4. Enviant preview a Telegram...")
    send_preview_to_telegram(output_img, caption)

    if os.path.exists(output_img):
        os.remove(output_img)


if __name__ == "__main__":
    main()
