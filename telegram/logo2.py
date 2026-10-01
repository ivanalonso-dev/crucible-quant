from PIL import Image, ImageDraw, ImageFilter
import math, numpy as np
S=2048; C=S//2
CYAN=(0,240,255); MAG=(255,40,200); VIOL=(140,80,255)

def fondo():
    y,x=np.mgrid[0:S,0:S]
    d=np.hypot(x-C,y-C)/(S*0.7)
    k=np.clip(1-d,0,1)
    a=np.zeros((S,S,3),dtype=np.uint8)
    a[...,0]=(4+14*k).astype(np.uint8); a[...,1]=(6+10*k).astype(np.uint8); a[...,2]=(16+44*k).astype(np.uint8)
    return Image.fromarray(a).convert("RGBA")

def neon(img, dibujar, color, blur=30, fuerza=2):
    capa=Image.new("RGBA",(S,S),(0,0,0,0)); dibujar(ImageDraw.Draw(capa), color)
    h=capa.filter(ImageFilter.GaussianBlur(blur))
    for _ in range(fuerza): img=Image.alpha_composite(img,h)
    return Image.alpha_composite(img,capa)

def onda(cx, cy, ancho, alto):
    xs=np.linspace(-1,1,400)
    env=np.exp(-(xs/0.32)**2)                      # envolvente: pico en el centro, simétrico
    ys=np.sin(xs*math.pi*7)*env
    return [(cx+x*ancho/2, cy-y*alto/2) for x,y in zip(xs,ys)]

def gradiente_linea(img, pts, c1, c2, w):
    d=ImageDraw.Draw(img); n=len(pts)
    for i in range(n-1):
        t=i/(n-2); c=tuple(int(c1[j]+(c2[j]-c1[j])*t) for j in range(3))
        d.line([pts[i],pts[i+1]],fill=c+(255,),width=w)

def guardar(img, nombre):
    out=img.convert("RGB").resize((640,640),Image.LANCZOS); out.save(nombre)
    m=Image.new("L",(640,640),0); ImageDraw.Draw(m).ellipse([0,0,640,640],fill=255)
    p=Image.new("RGB",(640,640),(255,255,255)); p.paste(out,(0,0),m); return p

# ---------------- A: HUD / radar
img=fondo()
def anillos(d,c):
    for r,w in [(760,6),(640,3),(470,4)]:
        d.ellipse([C-r,C-r,C+r,C+r],outline=c+(170,),width=w)
    for k in range(72):                              # marcas del radar
        a=math.radians(k*5); r1=700; r2=740 if k%6 else 690
        d.line([(C+r1*math.cos(a),C+r1*math.sin(a)),(C+r2*math.cos(a),C+r2*math.sin(a))],fill=c+(200,),width=5 if k%6==0 else 3)
    for a0,a1 in [(200,320),(20,140)]:               # arcos gruesos del HUD
        d.arc([C-850,C-850,C+850,C+850],a0,a1,fill=c+(230,),width=18)
img=neon(img,anillos,CYAN,blur=22,fuerza=1)
pts=onda(C,C,1150,760)
def trazar(d,c): d.line(pts,fill=c+(255,),width=34,joint="curve")
img=neon(img,trazar,MAG,blur=45,fuerza=2)
gradiente_linea(img,pts,CYAN,MAG,16)
d=ImageDraw.Draw(img)
for (x,y) in [pts[200]]:
    d.ellipse([x-30,y-30,x+30,y+30],fill=(255,255,255,255))
prevA=guardar(img,"crucible_futurista_A.png")

# ---------------- B: núcleo hexagonal
img=fondo()
def hexa(r, rot=30):
    return [(C+r*math.cos(math.radians(60*k+rot)),C+r*math.sin(math.radians(60*k+rot))) for k in range(6)]
def rejilla(d,c):
    for r,w,al in [(820,8,230),(700,3,140),(560,3,90)]:
        h=hexa(r); d.line(h+[h[0]],fill=c+(al,),width=w,joint="curve")
    h=hexa(820)
    for p in h: d.ellipse([p[0]-18,p[1]-18,p[0]+18,p[1]+18],fill=c+(255,))
    for i in range(6):                                # líneas de circuito hacia el centro
        a,b=hexa(820)[i],hexa(560)[i]; d.line([a,b],fill=c+(120,),width=3)
img=neon(img,rejilla,VIOL,blur=26,fuerza=1)
pts=onda(C,C,1000,700)
img=neon(img,lambda d,c: d.line(pts,fill=c+(255,),width=34,joint="curve"),CYAN,blur=45,fuerza=2)
gradiente_linea(img,pts,CYAN,(210,255,255),14)
d=ImageDraw.Draw(img)
for x,y in [pts[200]]:
    d.ellipse([x-28,y-28,x+28,y+28],fill=(255,255,255,255))
prevB=guardar(img,"crucible_futurista_B.png")

# comparativa lado a lado
comp=Image.new("RGB",(1340,700),(255,255,255)); comp.paste(prevA,(20,30)); comp.paste(prevB,(680,30))
comp.save("/tmp/claude-0/comparativa.png")
