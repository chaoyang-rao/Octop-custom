"""Two original geometric avatar loops. No extracted artwork or app code is used.

Single geometry/motion source for transparent PNG, WebP, GIF and animated SVG.
Run: python3 source/render_avatars.py
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
FINAL = ROOT / "final-v2"
QA = ROOT / "qa-v2"
SIZE, AA, FPS, SECONDS = 512, 3, 25, 6
TAU = math.tau


def smooth(x):
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)


def window(t, start, end, ramp=0.25):
    return smooth((t - start) / ramp) * smooth((end - t) / ramp)


def pulse(t, center, width):
    x = abs(t - center) / (width / 2)
    return (1 + math.cos(math.pi * x)) / 2 if x < 1 else 0.0


def rounded_polygon(vertices, amount=0.21, steps=12):
    result = []
    for i, v in enumerate(vertices):
        prev, nxt = vertices[i - 1], vertices[(i + 1) % len(vertices)]
        a = (v[0] + (prev[0] - v[0]) * amount, v[1] + (prev[1] - v[1]) * amount)
        b = (v[0] + (nxt[0] - v[0]) * amount, v[1] + (nxt[1] - v[1]) * amount)
        for j in range(steps + 1):
            u = j / steps
            result.append(((1-u)**2*a[0] + 2*u*(1-u)*v[0] + u*u*b[0],
                           (1-u)**2*a[1] + 2*u*(1-u)*v[1] + u*u*b[1]))
    return result


JADE = rounded_polygon([(-104, -175), (77, -172), (176, -66),
                        (161, 101), (33, 177), (-126, 130), (-183, -29)])


def capsule(cx, cy, width, height, angle):
    radius = min(width, height) / 2
    result = []
    # Fixed vertex count, including closed eyelids, for SVG path interpolation.
    for q, (sx, sy) in enumerate([(1, 1), (-1, 1), (-1, -1), (1, -1)]):
        ox, oy = sx * (width / 2 - radius), sy * (height / 2 - radius)
        for j in range(9):
            a = (q * 90 + j * 90 / 8) * math.pi / 180
            x, y = ox + radius * math.cos(a), oy + radius * math.sin(a)
            result.append((cx + x*math.cos(angle)-y*math.sin(angle),
                           cy + x*math.sin(angle)+y*math.cos(angle)))
    return result


def geometry(kind, t):
    t %= SECONDS
    p = TAU * t / SECONDS
    breath = math.sin(p)
    if kind == "momo":
        look = window(t, 2.15, 3.65, .35)
        look_back = window(t, 4.9, 5.7, .22)
        angle = math.radians(-4.5 + 2.2 * math.sin(p) + 4.1 * look)
        sx, sy = 1 + .013*breath, 1 + .017*breath
        cy = 266 + 3.0 * math.sin(p)
        body = []
        for i in range(144):
            a = TAU * i / 144
            r = 1 + .032*math.sin(3*a+.28) + .017*math.cos(5*a-.4)
            r += .006 * math.sin(2*a+p)  # subtle volume change
            body.append((184*r*math.cos(a), 180*r*math.sin(a)))
        blink = max(pulse(t, 1.26, .24), pulse(t, 1.62, .21), pulse(t, 4.5, .25))
        h0 = h1 = 54*(1-blink)+3.5*blink
        gx, gy = 10*look-4*look_back, -4*look
        eyes = [capsule(10+gx, -52+gy, 54, h0, 0),
                capsule(83+gx, -58+gy, 54, h1, 0)]
        layers = [("body", body, "#191b20", "#3b3e45", 1.2),
                  ("eye-left", eyes[0], "#fffdf7", None, 0),
                  ("eye-right", eyes[1], "#fffdf7", None, 0)]
    else:
        look_l = window(t, .4, 1.65, .3)
        look_r = window(t, 3.2, 4.35, .3)
        jump_u = (t-2.12)/.86
        jump = math.sin(math.pi*jump_u)**2 if 0 < jump_u < 1 else 0
        anticipate = pulse(t, 2.04, .32)
        land = pulse(t, 3.03, .28)
        squash = anticipate*.065 + land*.055
        angle = math.radians(3.5 + 3.1*math.sin(p) - 3.8*look_l + 4*look_r)
        sx = 1 + .014*breath + squash*.7 - jump*.018
        sy = 1 + .014*breath - squash + jump*.035
        cy = 268 + 2*math.sin(p) - 23*jump
        body = [(x*(1+.003*math.sin(p)), y) for x,y in JADE]
        blink = max(pulse(t, .98, .23), pulse(t, 4.95, .24))
        wink = pulse(t, 3.76, .38)
        h0 = 52*(1-blink)+3.5*blink
        h1 = 52*(1-max(blink,wink))+3.5*max(blink,wink)
        gx, gy = -11*look_l+9*look_r, -3*jump+2*look_l
        eyes = [capsule(-4+gx, -48+gy, 52, h0, 0),
                capsule(67+gx, -52+gy, 52, h1, 0)]
        layers = [("body", body, "#17bca7", "#169e8d", 1),
                  ("facet-left", [(-240,-210),(15,-210),(-33,6),(-230,72)], "#12b29f", None, 0),
                  ("facet-right", [(120,-220),(240,-150),(250,220),(86,220),(40,28)], "#20c3ae", None, 0),
                  ("eye-left", eyes[0], "#fffdf7", None, 0),
                  ("eye-right", eyes[1], "#fffdf7", None, 0)]
    def transform(points):
        out = []
        for x,y in points:
            x,y=x*sx,y*sy
            out.append((256+x*math.cos(angle)-y*math.sin(angle),
                        cy+x*math.sin(angle)+y*math.cos(angle)))
        return out
    return [(name,transform(points),fill,stroke,width) for name,points,fill,stroke,width in layers]


def render(kind, t):
    canvas = Image.new("RGBA", (SIZE*AA,SIZE*AA))
    layers = geometry(kind,t)
    bodymask=Image.new("L",canvas.size)
    for name,points,fill,stroke,width in layers:
        xy=[(round(x*AA),round(y*AA)) for x,y in points]
        layer=Image.new("RGBA",canvas.size)
        draw=ImageDraw.Draw(layer)
        draw.polygon(xy,fill=fill)
        if name.startswith("facet"):
            layer.putalpha(Image.composite(layer.getchannel("A"),Image.new("L",canvas.size),bodymask))
        if stroke:
            draw.line(xy+[xy[0]],fill=stroke,width=max(1,round(width*AA)),joint="curve")
        canvas=Image.alpha_composite(canvas,layer)
        if name=="body": ImageDraw.Draw(bodymask).polygon(xy,fill=255)
    return canvas.resize((SIZE,SIZE),Image.Resampling.LANCZOS)


def d(points):
    return "M" + "L".join(f"{x:.2f},{y:.2f}" for x,y in points) + "Z"


def svg(kind, title):
    n=SECONDS*FPS
    frames=[geometry(kind,i/FPS) for i in range(n+1)]
    paths=[]
    for idx,(name,points,fill,stroke,width) in enumerate(frames[0]):
        values=";".join(d(f[idx][1]) for f in frames)
        clip=' clip-path="url(#body-clip)"' if name.startswith('facet') else ''
        extra=f' stroke="{stroke}" stroke-width="{width}" stroke-linejoin="round"' if stroke else ''
        anim=f'<animate attributeName="d" values="{values}" dur="6s" repeatCount="indefinite" calcMode="linear"/>'
        paths.append(f'<path id="{name}" d="{d(points)}" fill="{fill}"{extra}{clip}>{anim}</path>')
    bodyvalues=";".join(d(f[0][1]) for f in frames)
    clip=f'<defs><clipPath id="body-clip"><path d="{d(frames[0][0][1])}"><animate attributeName="d" values="{bodyvalues}" dur="6s" repeatCount="indefinite"/></path></clipPath></defs>'
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 512 512" role="img" aria-label="{title}"><title>{title}</title>{clip}{"".join(paths)}</svg>'


def gif_frame(frame):
    alpha=frame.getchannel('A')
    # GIF has binary alpha; WebP/SVG retain smooth full alpha.
    pal=frame.convert('RGB').quantize(colors=127,method=Image.Quantize.MEDIANCUT)
    table=pal.getpalette()[:381]
    indices=bytes(0 if a<128 else v+1 for v,a in zip(pal.tobytes(),alpha.tobytes()))
    out=Image.frombytes('P',frame.size,indices)
    out.putpalette(([0,0,0]+table+[0]*768)[:768])
    out.info['transparency']=0
    return out


def main(verify_only=False):
    FINAL.mkdir(parents=True,exist_ok=True)
    QA.mkdir(parents=True,exist_ok=True)
    meta=[]
    contact=Image.new('RGB',(6*256,2*286),'#f4f4f1')
    for row,(kind,name,title) in enumerate([('momo','01-momo','墨团'),('jade','02-jade','青石')]):
        count=SECONDS*FPS
        if not verify_only:
            frames=[render(kind,i/FPS) for i in range(count)]
            frames[0].save(FINAL/f'{name}.png')
            frames[0].save(FINAL/f'{name}.webp',save_all=True,append_images=frames[1:],duration=1000//FPS,
                           loop=0,lossless=True,method=4,exact=True)
            gifs=[gif_frame(f) for f in frames]
            gifs[0].save(FINAL/f'{name}.gif',save_all=True,append_images=gifs[1:],duration=1000//FPS,
                         loop=0,transparency=0,disposal=2,optimize=False)
            (FINAL/f'{name}.svg').write_text(svg(kind,title))
        for col,t in enumerate([0,.98,1.26,2.55,3.76,4.95]):
            f=render(kind,t).resize((256,256),Image.Resampling.LANCZOS)
            contact.paste(f,(col*256,row*286),f)
            ImageDraw.Draw(contact).text((col*256+16,row*286+257),f'{title} / {t:.2f}s',fill='#444444')
        encoded={}
        for extension in ('webp','gif'):
            with Image.open(FINAL/f'{name}.{extension}') as im:
                assert im.is_animated and 1 < im.n_frames <= count
                encoded[extension]=im.n_frames
                duration=0
                for i in range(im.n_frames):
                    im.seek(i); im.load()
                    duration+=im.info.get('duration',0)
                assert duration==SECONDS*1000, (name,extension,duration)
                assert im.convert('RGBA').getextrema()[3][0]==0
        assert geometry(kind,0)==geometry(kind,SECONDS)
        # Seam should be a normal adjacent movement, not a jump cut.
        def avgdelta(a,b):
            return sum(math.hypot(x-u,y-v) for (x,y),(u,v) in zip(a[0][1],b[0][1]))/len(a[0][1])
        deltas=[avgdelta(geometry(kind,i/FPS),geometry(kind,(i+1)/FPS)) for i in range(count)]
        assert deltas[-1]<=max(deltas)*1.05
        meta.append({'name':title,'stem':name,'size':[SIZE,SIZE],'sampled_frames':count,'encoded_frames':encoded,'fps':FPS,
                     'duration_seconds':SECONDS,'transparent':True,'loop_seam_body_px':round(deltas[-1],4),
                     'formats':['webp','gif','svg','png']})
        print(title,[(p.suffix,round(p.stat().st_size/1024)) for p in FINAL.glob(name+'.*')])
    contact.save(QA/'motion-contact-sheet.png')
    (QA/'asset-checks.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2))


if __name__=='__main__': main(verify_only='--verify-only' in sys.argv)
