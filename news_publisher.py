import os
import json
import time
import requests
import textwrap
import subprocess
from PIL import Image, ImageDraw, ImageFont
from google import genai
from google.genai import types

# --- CONFIGURACIÓ ---
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
PEXELS_API_KEY = os.getenv('PEXELS_API_KEY')
BUFFER_ACCESS_TOKEN = os.getenv('BUFFER_ACCESS_TOKEN')
BUFFER_CHANNEL_ID = os.getenv('BUFFER_CHANNEL_ID')
GITHUB_REPOSITORY = os.getenv('GITHUB_REPOSITORY')

BRAND_NAME = "EL TEU COMPTE"  # Canvia-ho pel nom del teu compte
IMAGES_DIR = 'images'

def setup_workspace():
    if not os.path.exists(IMAGES_DIR):
        os.makedirs(IMAGES_DIR)
    else:
        for f in os.listdir(IMAGES_DIR):
            fp = os.path.join(IMAGES_DIR, f)
            if os.path.isfile(fp):
                os.remove(fp)

def generate_satirical_news():
    client = genai.Client(api_key=GEMINI_API_KEY)
    prompt = """
    Ets un guionista d'un diari satíric d'humor absurd (estil El Mundo Today / The Onion) centrat en intel·ligència artificial, tecnologia i cultura d'internet.
    
    Genera una notícia satírica breu. Respon ÚNICAMENT en format JSON amb aquestes claus:
    - "titular": Titular sensacionalista i absurd en majúscules (màxim 12 paraules).
    - "cerca_imatge": Paraules clau senzilles en anglès per cercar una foto realista a Pexels (ex: "tired programmer laptop", "businessman crying", "modern server room").
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

    # Escalar i retallar a 4:5
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

    # Degradat negre inferior
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

    # Dibuix del titular
    lines = textwrap.wrap(titular.upper(), width=22)
    text_y = brand_y + 55
    for line in lines:
        bbox_l = draw.textbbox((0, 0), line, font=font_headline)
        lw = bbox_l[2] - bbox_l[0]
        lh = bbox_l[3] - bbox_l[1]
        draw.text(((CANVAS_W - lw) / 2, text_y), line, font=font_headline, fill=(255, 255, 255))
        text_y += lh + 18

    output_path = os.path.join(IMAGES_DIR, "news_post.jpg")
    final_img.save(output_path, quality=95)
    
    if os.path.exists(stock_path):
        os.remove(stock_path)
    return output_path

def push_image_to_github(filepath):
    subprocess.run(["git", "config", "--local", "user.email", "bot@github.com"], check=True)
    subprocess.run(["git", "config", "--local", "user.name", "NewsBot"], check=True)
    
    subprocess.run(["git", "add", "-f", filepath], check=True)
    commit_res = subprocess.run(["git", "commit", "-m", "Nova notícia generada [skip ci]"])
    if commit_res.returncode == 0:
        subprocess.run(["git", "push"], check=True)
        time.sleep(5)
    
    filename = os.path.basename(filepath)
    return f"https://raw.githubusercontent.com/{GITHUB_REPOSITORY}/main/images/{filename}"

def publish_image_to_buffer(image_url, caption):
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
            "assets": [{"image": {"url": image_url}}],
            "metadata": {"instagram": {"type": "post"}}
        }
    }
    headers = {"Authorization": f"Bearer {BUFFER_ACCESS_TOKEN}", "Content-Type": "application/json"}
    res = requests.post("https://api.buffer.com", json={"query": query, "variables": variables}, headers=headers).json()
    
    if "errors" in res: raise Exception(f"Error GraphQL: {res['errors']}")
    post_data = res.get("data", {}).get("createPost", {})
    if "message" in post_data: raise Exception(f"Error Buffer: {post_data['message']}")

    print("🚀 Notícia publicada directament al Feed d'Instagram!")

def main():
    setup_workspace()
    print("1. Demanant notícia a Gemini...")
    titular, keyword, caption = generate_satirical_news()
    print(f"Titular: {titular}")

    print("2. Descarregant foto d'estoc de Pexels...")
    stock_file = download_pexels_image(keyword)

    print("3. Generant composició gràfica...")
    final_img_path = render_news_image(stock_file, titular, BRAND_NAME)

    print("4. Pujant imatge temporal a GitHub...")
    raw_url = push_image_to_github(final_img_path)

    print("5. Publicant post a Buffer...")
    publish_image_to_buffer(raw_url, caption)

if __name__ == "__main__":
    main()
