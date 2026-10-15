"""Genera l'icona dell'app: quadrato arrotondato teal + onda audio bianca.
Produce packaging/icon.png (anteprima) e packaging/icon.ico (multi-risoluzione)."""
from pathlib import Path
from PIL import Image, ImageDraw

OUT = Path(__file__).parent
S = 1024  # render ad alta risoluzione, poi si ridimensiona (bordi netti)

# --- sfondo: gradiente teal verticale (tema app, accento #0f9d8f) ---
top = (20, 190, 170)     # teal un filo piu' chiaro in alto
bot = (11, 120, 109)     # teal piu' scuro in basso (profondita')
col = Image.new("RGB", (1, S))
for y in range(S):
    t = y / (S - 1)
    col.putpixel((0, y), tuple(int(top[i] * (1 - t) + bot[i] * t) for i in range(3)))
grad = col.resize((S, S)).convert("RGBA")

# --- maschera quadrato arrotondato (squircle-like) ---
mask = Image.new("L", (S, S), 0)
ImageDraw.Draw(mask).rounded_rectangle([0, 0, S - 1, S - 1], radius=int(S * 0.225), fill=255)
img = Image.composite(grad, Image.new("RGBA", (S, S), (0, 0, 0, 0)), mask)

# --- onda audio: barre bianche a cappello tondo, profilo a "picco" ---
draw = ImageDraw.Draw(img)
heights = [0.34, 0.58, 0.82, 1.0, 0.78, 0.52, 0.38]   # frazioni dell'altezza max
bar_w = int(S * 0.07)
gap = int(S * 0.045)
n = len(heights)
total_w = n * bar_w + (n - 1) * gap
x = (S - total_w) // 2
cy = S // 2
for h in heights:
    bh = int(S * 0.56 * h)
    draw.rounded_rectangle([x, cy - bh // 2, x + bar_w, cy + bh // 2],
                           radius=bar_w // 2, fill=(255, 255, 255, 255))
    x += bar_w + gap

img.save(OUT / "icon.png")
img.save(OUT / "icon.ico", sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
print("creati:", OUT / "icon.png", "|", OUT / "icon.ico")
