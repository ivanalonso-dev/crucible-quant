"""Banner para X (Twitter): 1500x500. La foto de perfil tapa la esquina inferior izquierda,
así que el texto va en el centro y el emblema a la derecha."""
from PIL import Image, ImageDraw, ImageFilter, ImageFont
import math, numpy as np
SC = 3
W, H = 1500 * SC, 500 * SC
CYAN = (0, 240, 255); MAG = (255, 40, 200); VIOL = (140, 80, 255)
FB = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FL = "/usr/share/fonts/truetype/dejavu/DejaVuSans-ExtraLight.ttf"


def fondo():
    y, x = np.mgrid[0:H, 0:W]
    d = np.hypot((x - W * 0.78) / W, (y - H / 2) / H) / 0.7
    k = np.clip(1 - d, 0, 1)
    a = np.zeros((H, W, 3), dtype=np.uint8)
    a[..., 0] = 4 + 14 * k; a[..., 1] = 6 + 10 * k; a[..., 2] = 16 + 46 * k
    img = Image.fromarray(a).convert("RGBA")
    g = ImageDraw.Draw(img)
    for x in range(0, W, 90): g.line([(x, 0), (x, H)], fill=(40, 60, 110, 40), width=2)
    for y in range(0, H, 90): g.line([(0, y), (W, y)], fill=(40, 60, 110, 40), width=2)
    return img


def neon(img, f, col, blur=25, veces=2):
    c = Image.new("RGBA", (W, H), (0, 0, 0, 0)); f(ImageDraw.Draw(c), col)
    h = c.filter(ImageFilter.GaussianBlur(blur))
    for _ in range(veces): img = Image.alpha_composite(img, h)
    return Image.alpha_composite(img, c)


def onda(cx, cy, ancho, alto):
    xs = np.linspace(-1, 1, 400); env = np.exp(-(xs / 0.32) ** 2); ys = np.sin(xs * math.pi * 7) * env
    return [(cx + x * ancho / 2, cy - y * alto / 2) for x, y in zip(xs, ys)]


def grad(img, pts, c1, c2, w):
    d = ImageDraw.Draw(img)
    for i in range(len(pts) - 1):
        t = i / (len(pts) - 2)
        d.line([pts[i], pts[i + 1]], fill=tuple(int(c1[j] + (c2[j] - c1[j]) * t) for j in range(3)) + (255,), width=w)


def textos(img, acento):
    x0 = 1230
    f1 = ImageFont.truetype(FB, 190); f2 = ImageFont.truetype(FL, 78); f3 = ImageFont.truetype(FB, 66)
    def t(d, c): d.text((x0, 300), "CRUCIBLE QUANT", font=f1, fill=c + (255,))
    img = neon(img, t, acento, blur=26, veces=1)
    d = ImageDraw.Draw(img)
    d.text((x0, 300), "CRUCIBLE QUANT", font=f1, fill=(245, 250, 255, 255))
    d.line([(x0, 545), (x0 + 1640, 545)], fill=acento + (255,), width=8)
    d.text((x0, 590), "Daily volatility alerts · Top 30 crypto", font=f2, fill=(210, 225, 245, 255))
    d.text((x0, 700), "Direction-neutral · Not financial advice", font=f2, fill=(160, 180, 215, 255))
    d.text((x0, 850), "±8% · 7 DAYS  ·  30-DAY FREE TRIAL", font=f3, fill=acento + (255,))
    return img


def guardar(img, nombre):
    img.convert("RGB").resize((1500, 500), Image.LANCZOS).save(nombre)


cx, cy, R = 3780, 750, 1.45   # emblema a la derecha

# A: HUD (cian + magenta)
img = fondo()
def hud(d, c):
    for r, w in [(400, 8), (330, 5), (250, 5)]:
        r *= R; d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=c + (170,), width=w)
    for k in range(72):
        a = math.radians(k * 5); r1, r2 = 365 * R, (385 if k % 6 else 355) * R
        d.line([(cx + r1 * math.cos(a), cy + r1 * math.sin(a)), (cx + r2 * math.cos(a), cy + r2 * math.sin(a))],
               fill=c + (200,), width=6 if k % 6 == 0 else 3)
    for a0, a1 in [(200, 320), (20, 140)]:
        r = 450 * R; d.arc([cx - r, cy - r, cx + r, cy + r], a0, a1, fill=c + (230,), width=16)
img = neon(img, hud, CYAN, blur=24, veces=1)
p = onda(cx, cy, 620 * R, 420 * R)
img = neon(img, lambda d, c: d.line(p, fill=c + (255,), width=28, joint="curve"), MAG, blur=40)
grad(img, p, CYAN, MAG, 13)
img = textos(img, CYAN)
guardar(img, "crucible_x_banner_A.png")

# B: hexágono (violeta + cian)
img = fondo()
def hexa(r, rot=30):
    return [(cx + r * R * math.cos(math.radians(60 * k + rot)), cy + r * R * math.sin(math.radians(60 * k + rot))) for k in range(6)]
def rej(d, c):
    for r, w, al in [(430, 9, 230), (360, 5, 140), (290, 5, 90)]:
        h = hexa(r); d.line(h + [h[0]], fill=c + (al,), width=w, joint="curve")
    for q in hexa(430): d.ellipse([q[0] - 16, q[1] - 16, q[0] + 16, q[1] + 16], fill=c + (255,))
    for i in range(6): d.line([hexa(430)[i], hexa(290)[i]], fill=c + (120,), width=3)
img = neon(img, rej, VIOL, blur=24, veces=1)
p = onda(cx, cy, 540 * R, 380 * R)
img = neon(img, lambda d, c: d.line(p, fill=c + (255,), width=28, joint="curve"), CYAN, blur=40)
grad(img, p, CYAN, (210, 255, 255), 12)
img = textos(img, VIOL)
guardar(img, "crucible_x_banner_B.png")
