"""Composite rendered RGBA frames onto a studio gradient and add captions.
usage: python3 scripts/composite.py <render_dir> <out_dir>"""
import sys, os, glob, math
from PIL import Image, ImageDraw, ImageFont, ImageFilter

SRC, DST = sys.argv[1], sys.argv[2]
os.makedirs(DST, exist_ok=True)
W, H = 1080, 1920
FONT_B = "/usr/share/fonts/opentype/inter/Inter-SemiBold.otf"
FONT_X = "/usr/share/fonts/opentype/inter/InterDisplay-Bold.otf"
FONT_R = "/usr/share/fonts/opentype/inter/Inter-Medium.otf"

def font(p, s):
    try: return ImageFont.truetype(p, s)
    except OSError: return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", s)

# studio background: vertical gradient + soft vignette (like a viewport backdrop)
bg = Image.new("RGB", (W, H))
px = bg.load()
for y in range(H):
    t = y / (H - 1)
    top, bot = (52, 54, 58), (24, 25, 28)
    c = tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3))
    for x in range(W): px[x, y] = c
vig = Image.new("L", (W, H), 0)
ImageDraw.Draw(vig).ellipse((-W * 0.35, -H * 0.15, W * 1.35, H * 1.15), fill=255)
vig = vig.filter(ImageFilter.GaussianBlur(220))
bg = Image.composite(bg, Image.new("RGB", (W, H), (14, 15, 17)), vig)

# (start, end, step-number or None, text)
CAPS = [
    (1, 66, None, "Glock 18 – so funktioniert's"),
    (72, 112, None, "Schnittansicht"),
    (112, 166, 1, "Abzug wird gezogen –\nAbzugsstange spannt den Schlagbolzen"),
    (166, 186, 2, "Abzugsstange senkt sich –\nSchlagbolzen schnellt nach vorn"),
    (186, 208, 3, "Schlagbolzen trifft das Zündhütchen"),
    (208, 240, 4, "Pulvergase treiben das Projektil\ndurch den Lauf"),
    (240, 262, 5, "Schuss verlässt die Mündung"),
    (262, 306, 6, "Schlitten fährt zurück – Hülse fliegt raus,\nneue Patrone wird zugeführt"),
    (306, 352, None, "Bereit für den nächsten Schuss"),
]
FADE = 6

def caption(img, text, num, alpha):
    if alpha <= 0: return
    f = font(FONT_B, 46)
    d0 = ImageDraw.Draw(img)
    lines = text.split("\n")
    lw = max(d0.textlength(l, font=f) for l in lines)
    lh = 58
    badge = 70 if num else 0
    pw, ph = int(lw + 64 + badge), int(lh * len(lines) + 40)
    x0, y0 = (W - pw) // 2, 230
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.rounded_rectangle((x0 + 4, y0 + 8, x0 + pw + 4, y0 + ph + 8), 18, fill=(0, 0, 0, int(70 * alpha)))
    d.rounded_rectangle((x0, y0, x0 + pw, y0 + ph), 18, fill=(255, 255, 255, int(255 * alpha)))
    tx = x0 + 32 + badge
    if num:
        cy = y0 + ph // 2
        d.ellipse((x0 + 26, cy - 26, x0 + 78, cy + 26), fill=(150, 56, 33, int(255 * alpha)))
        nf = font(FONT_X, 34)
        d.text((x0 + 52, cy), str(num), font=nf, fill=(255, 255, 255, int(255 * alpha)), anchor="mm")
    for i, l in enumerate(lines):
        d.text((tx, y0 + 20 + i * lh), l, font=f, fill=(12, 12, 14, int(255 * alpha)))
    img.alpha_composite(layer)

def title(img, alpha):
    if alpha <= 0: return
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0)); d = ImageDraw.Draw(layer)
    a = int(255 * alpha)
    d.text((W // 2, 300), "GLOCK 18", font=font(FONT_X, 120), fill=(236, 236, 238, a), anchor="mm")
    d.text((W // 2, 395), "Vom Abzug bis zur Mündung", font=font(FONT_R, 44), fill=(190, 192, 198, a), anchor="mm")
    d.line((W // 2 - 90, 455, W // 2 + 90, 455), fill=(150, 56, 33, a), width=5)
    img.alpha_composite(layer)

files = sorted(glob.glob(os.path.join(SRC, "f*.png")))
for fp in files:
    f = int(os.path.basename(fp)[1:5])
    rgba = Image.open(fp).convert("RGBA")
    if rgba.size != (W, H): rgba = rgba.resize((W, H), Image.LANCZOS)
    out = bg.convert("RGBA")
    out.alpha_composite(rgba)
    for s, e, n, t in CAPS:
        if s <= f <= e:
            a = min(1, (f - s) / FADE + 0.001 if s > 1 else 1, (e - f) / FADE)
            caption(out, t, n, max(0, a))
    title(out, min(1, max(0, (f - 372) / 18)))
    out.convert("RGB").save(os.path.join(DST, f"f{f:04d}.png"))
print("composited", len(files))
