from PIL import Image, ImageDraw, ImageFilter, ImageFont
import math, numpy as np
W,H=1920,1080; SC=3                     # se dibuja a 3x y se reduce a 640x360
CYAN=(0,240,255); MAG=(255,40,200); VIOL=(140,80,255)
FB="/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"; FL="/usr/share/fonts/truetype/dejavu/DejaVuSans-ExtraLight.ttf"

def fondo():
    y,x=np.mgrid[0:H,0:W]
    d=np.hypot((x-W*0.3)/W,(y-H/2)/H)/0.8; k=np.clip(1-d,0,1)
    a=np.zeros((H,W,3),dtype=np.uint8)
    a[...,0]=(4+14*k); a[...,1]=(6+10*k); a[...,2]=(16+46*k)
    img=Image.fromarray(a).convert("RGBA")
    g=ImageDraw.Draw(img)
    for x in range(0,W,80): g.line([(x,0),(x,H)],fill=(40,60,110,40),width=1)
    for y in range(0,H,80): g.line([(0,y),(W,y)],fill=(40,60,110,40),width=1)
    return img

def neon(img,f,col,blur=25,veces=2):
    c=Image.new("RGBA",(W,H),(0,0,0,0)); f(ImageDraw.Draw(c),col)
    h=c.filter(ImageFilter.GaussianBlur(blur))
    for _ in range(veces): img=Image.alpha_composite(img,h)
    return Image.alpha_composite(img,c)

def onda(cx,cy,ancho,alto):
    xs=np.linspace(-1,1,400); env=np.exp(-(xs/0.32)**2); ys=np.sin(xs*math.pi*7)*env
    return [(cx+x*ancho/2,cy-y*alto/2) for x,y in zip(xs,ys)]

def grad(img,pts,c1,c2,w):
    d=ImageDraw.Draw(img)
    for i in range(len(pts)-1):
        t=i/(len(pts)-2); d.line([pts[i],pts[i+1]],fill=tuple(int(c1[j]+(c2[j]-c1[j])*t) for j in range(3))+(255,),width=w)

def textos(img,acento):
    d=ImageDraw.Draw(img)
    x0=990
    f1=ImageFont.truetype(FB,120); f2=ImageFont.truetype(FL,50); f3=ImageFont.truetype(FB,40)
    def t(d,c): d.text((x0,330),"CRUCIBLE",font=f1,fill=c+(255,)); d.text((x0,460),"QUANT",font=f1,fill=c+(255,))
    img=neon(img,t,acento,blur=18,veces=1)
    d=ImageDraw.Draw(img)
    d.text((x0,330),"CRUCIBLE",font=f1,fill=(245,250,255,255)); d.text((x0,460),"QUANT",font=f1,fill=(245,250,255,255))
    d.line([(x0,620),(x0+760,620)],fill=acento+(255,),width=5)
    d.text((x0,650),"Daily volatility alerts",font=f2,fill=(210,225,245,255))
    d.text((x0,725),"Top 30 crypto · direction-neutral",font=f2,fill=(160,180,215,255))
    d.text((x0,835),"±8% · 7 DAYS",font=f3,fill=acento+(255,))
    return img

def guardar(img,nombre):
    img.convert("RGB").resize((640,360),Image.LANCZOS).save(nombre)

# A: HUD
img=fondo(); cx,cy=500,540
def hud(d,c):
    for r,w in [(400,5),(330,3),(250,3)]: d.ellipse([cx-r,cy-r,cx+r,cy+r],outline=c+(170,),width=w)
    for k in range(72):
        a=math.radians(k*5); r1,r2=365,(385 if k%6 else 355)
        d.line([(cx+r1*math.cos(a),cy+r1*math.sin(a)),(cx+r2*math.cos(a),cy+r2*math.sin(a))],fill=c+(200,),width=4 if k%6==0 else 2)
    for a0,a1 in [(200,320),(20,140)]: d.arc([cx-450,cy-450,cx+450,cy+450],a0,a1,fill=c+(230,),width=12)
img=neon(img,hud,CYAN,blur=18,veces=1)
p=onda(cx,cy,620,420)
img=neon(img,lambda d,c: d.line(p,fill=c+(255,),width=20,joint="curve"),MAG,blur=30)
grad(img,p,CYAN,MAG,9)
img=textos(img,CYAN)
guardar(img,"crucible_banner_A.png")

# B: hexágono
img=fondo(); cx,cy=500,540
def hexa(r,rot=30): return [(cx+r*math.cos(math.radians(60*k+rot)),cy+r*math.sin(math.radians(60*k+rot))) for k in range(6)]
def rej(d,c):
    for r,w,al in [(430,6,230),(360,3,140),(290,3,90)]:
        h=hexa(r); d.line(h+[h[0]],fill=c+(al,),width=w,joint="curve")
    for q in hexa(430): d.ellipse([q[0]-11,q[1]-11,q[0]+11,q[1]+11],fill=c+(255,))
    for i in range(6): d.line([hexa(430)[i],hexa(290)[i]],fill=c+(120,),width=2)
img=neon(img,rej,VIOL,blur=18,veces=1)
p=onda(cx,cy,540,380)
img=neon(img,lambda d,c: d.line(p,fill=c+(255,),width=20,joint="curve"),CYAN,blur=30)
grad(img,p,CYAN,(210,255,255),8)
img=textos(img,VIOL)
guardar(img,"crucible_banner_B.png")

c=Image.new("RGB",(640,740),(255,255,255))
c.paste(Image.open("crucible_banner_A.png"),(0,0)); c.paste(Image.open("crucible_banner_B.png"),(0,380)); c.save("/tmp/claude-0/banners.png")
