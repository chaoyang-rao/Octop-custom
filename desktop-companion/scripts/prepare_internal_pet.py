"""Compile generated RGBA frame sheets for the private native pet bundle.

Only deterministic cell extraction and uniform resizing happen here. Character,
material, facial and limb changes come from the generated source artwork.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from sprite_layout import registration
import shutil

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
DELAYS = {"idle": 150, "walking": 130, "listening": 180, "thinking": 220,
          "working": 140, "speaking": 140, "success": 160, "error": 200, "sleeping": 500}


def cells(path: Path, columns: int, rows: int) -> list[Image.Image]:
    with Image.open(path) as source:
        image=source.convert("RGBA")
    if image.width < columns*64 or image.height < rows*64 or image.getchannel("A").getextrema()[0] != 0:
        raise ValueError(f"Expected a transparent, equal-cell sheet: {path.name}")
    width,height=image.width/columns,image.height/rows
    return [image.crop((round(x*width),round(y*height),round((x+1)*width),round((y+1)*height)))
            for y in range(rows) for x in range(columns)]


def compile_pet(source: Path, output: Path) -> dict:
    stage=output.with_name(output.name+".preparing")
    if stage.exists():
        raise ValueError("Review the unfinished internal frame build first")
    stage.mkdir(parents=True)
    animations={}
    inputs={}
    def save(name: str, frames: list[Image.Image], delay: int) -> None:
        names=[]
        for index,frame in enumerate(frames,1):
            filename=f"{name}-{index:02}.png"
            # Premultiplied resizing preserves the true-alpha contour.
            scaled=frame.convert("RGBa")
            scaled.thumbnail((512,512),Image.Resampling.LANCZOS)
            canvas=Image.new("RGBA",(512,512))
            canvas.paste(scaled.convert("RGBA"),((512-scaled.width)//2,(512-scaled.height)//2))
            canvas.save(stage/filename)
            names.append(filename)
        animations["sleep" if name=="sleeping" else name]={"frames":names,"frameDelay":delay}
    for name,delay in DELAYS.items():
        path=source/"sheets"/(name+".png")
        frames=cells(path,2,2)
        if name=="idle":
            blink=source/"sheets/idle-closed.png"
            with Image.open(blink) as image:
                frames=[frames[0],image.convert("RGBA")]
            inputs[blink.name]=hashlib.sha256(blink.read_bytes()).hexdigest()
        save(name,frames,delay)
        inputs[path.name]=hashlib.sha256(path.read_bytes()).hexdigest()
    flight=source/"sheets/flight.png"
    frames=cells(flight,3,3)
    for index,name in enumerate(["takeoff","dragging","landing"]):
        save(name,frames[index*3:index*3+3],100)
    inputs["flight.png"]=hashlib.sha256(flight.read_bytes()).hexdigest()
    # Hold the open-eyed idle pose between the short blink frames.
    idle=animations["idle"]["frames"]
    animations["idle"].update(frames=[idle[0]]*20+[idle[1]],frameDelay=100,
                              baseFrame=idle[0],overlayRect=[236/512,106/512,78/512,34/512])
    manifest={"name":"哆啦 · 内部立体版","animations":animations}
    peek_source = source/"peek.json"
    if peek_source.is_file():
        peek = json.loads(peek_source.read_text())
        for item in peek.values():
            name = item["frame"]
            if Path(name).name != name or not name.endswith(".png"):
                raise ValueError("Invalid private peek frame path")
            shutil.copy2(source/"peek"/name, stage/name)
        manifest["peek"] = peek
    manifest["registration"], _ = registration(stage, manifest)
    (stage/"pet.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n")
    notice="""Dora internal 3D pet artwork

The sprite frames were newly generated with the built-in imagegen tool after
the user's approval of the character, 3D material and flight preview.
They do not bundle pixels from the earlier third-party sprite pack.

Intended distribution: the user's small internal team, non-commercial use.
Doraemon character rights remain with Fujiko F. Fujio / Shogakukan and the
respective rights holders. Generation does not grant character rights.
No MIT, CC0, or unrestricted-commercial license is assigned to this artwork.
This character pack and installers containing it are excluded from public Git.
"""
    (stage/"ASSET-NOTICE.txt").write_text(notice)
    files={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in stage.iterdir() if p.is_file()}
    report={"character":manifest["name"],"internal_only":True,"generated_with":"built-in imagegen",
            "states":len(animations),"unique_frames":len(list(stage.glob("*.png"))),
            "source_sheets":inputs,"files":files}
    (stage/"internal-art-manifest.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    if output.exists():
        backup=output.with_name(output.name+".previous")
        if backup.exists():raise ValueError("Review the previous internal frame backup first")
        output.rename(backup)
    stage.rename(output)
    return report


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source",type=Path,default=ROOT/"assets/internal/dora3d")
    parser.add_argument("--output",type=Path,default=ROOT/"assets/internal/dora3d/frames")
    args=parser.parse_args()
    report=compile_pet(args.source.resolve(),args.output.resolve())
    print(json.dumps({"states":report["states"],"unique_frames":report["unique_frames"],"output":str(args.output),"internal_only":True},ensure_ascii=False))


if __name__=="__main__":main()
