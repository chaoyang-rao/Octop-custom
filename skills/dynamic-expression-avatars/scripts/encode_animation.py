#!/usr/bin/env python3
"""Encode vector frames as genuine transparent PNG/WebP/GIF. Requires Pillow."""
import argparse,json
from pathlib import Path
from PIL import Image,ImageDraw

def render(frame,view,size):
    vx,vy,vw,vh=map(float,view.split());aa=2
    image=Image.new('RGBA',(size*aa,size*aa))
    def points(seq):return [((x-vx)*size*aa/vw,(y-vy)*size*aa/vh) for x,y in seq]
    mask=Image.new('L',image.size);ImageDraw.Draw(mask).polygon(points(frame['body']),fill=255)
    d=ImageDraw.Draw(image);d.polygon(points(frame['body']),fill=frame['base'])
    d.line(points(frame['body'])+[points(frame['body'])[0]],fill=frame['outline'],width=max(1,round(size*aa/vw)),joint='curve')
    for facet in frame['facets']:
        part=Image.new('RGBA',image.size);ImageDraw.Draw(part).polygon(points(facet['points']),fill=facet['fill'])
        part.putalpha(Image.composite(part.getchannel('A'),Image.new('L',image.size),mask));image=Image.alpha_composite(image,part)
    d=ImageDraw.Draw(image)
    for eye in frame['eyes']:d.polygon(points(eye),fill='#FFFDF7')
    return image.resize((size,size),Image.Resampling.LANCZOS)

def palettize(frame):
    alpha=frame.getchannel('A');q=frame.convert('RGB').quantize(colors=127)
    result=Image.frombytes('P',frame.size,bytes(0 if a<128 else v+1 for v,a in zip(q.tobytes(),alpha.tobytes())))
    result.putpalette(([0,0,0]+q.getpalette()[:381]+[0]*768)[:768]);result.info['transparency']=0
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('frames',type=Path);p.add_argument('--out',type=Path,required=True);p.add_argument('--size',type=int,default=512);p.add_argument('--formats',default='png,webp,gif');a=p.parse_args()
    data=json.loads(a.frames.read_text());formats=[x for x in dict.fromkeys(a.formats.split(',')) if x]
    if not formats or any(x not in ['png','webp','gif'] for x in formats):p.error('formats: png,webp,gif')
    if not 32<=a.size<=2048:p.error('size must be 32–2048')
    stem=f"{data['shape']}-{data['color']}";paths=[a.out/f'{stem}.{x}' for x in formats]
    if any(x.exists() for x in paths):p.error('output exists; choose a new directory')
    fps=data['fps'];raw=data['frames'];assert len(raw)==round(data['duration']*fps)
    images=[render(f,data['viewBox'],a.size) for f in raw]
    wm=[round((i+1)*1000/fps)-round(i*1000/fps) for i in range(len(images))]
    gm=[round((i+1)*100/fps)*10-round(i*100/fps)*10 for i in range(len(images))]
    a.out.mkdir(parents=True,exist_ok=True)
    if 'png' in formats:images[0].save(a.out/f'{stem}.png')
    if 'webp' in formats:images[0].save(a.out/f'{stem}.webp',save_all=True,append_images=images[1:],duration=wm,loop=0,lossless=True,method=4,exact=True)
    if 'gif' in formats:
        frames=[palettize(f) for f in images];frames[0].save(a.out/f'{stem}.gif',save_all=True,append_images=frames[1:],duration=gm,loop=0,transparency=0,disposal=2,optimize=False)
    checks=[]
    for file in paths:
        with Image.open(file) as im:
            if file.suffix!='.png':
                assert im.is_animated;total=0
                for i in range(im.n_frames):im.seek(i);im.load();total+=im.info.get('duration',0)
                assert total==round(data['duration']*1000),(file,total)
            assert im.convert('RGBA').getextrema()[3][0]==0
        checks.append({'path':str(file.resolve()),'bytes':file.stat().st_size})
    print(json.dumps({'checks':'passed','outputs':checks},ensure_ascii=False))

if __name__=='__main__':main()
