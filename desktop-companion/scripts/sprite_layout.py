"""Measure existing sprite landmarks and write layout metadata, never image pixels."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image


def measure(path: Path) -> dict:
    with Image.open(path) as source:
        image = source.convert("RGBA")
    width, height = image.size
    pixels = image.load()
    red = {
        (x, y)
        for y in range(int(height * .6))
        for x in range(int(width * .15), int(width * .85))
        if pixels[x, y][3] > 180 and pixels[x, y][0] > 145
        and pixels[x, y][1] < 135 and pixels[x, y][2] < 150
        and pixels[x, y][0] > pixels[x, y][1] * 1.3
    }
    noses = []
    while red:
        stack = [red.pop()]
        component = stack[:]
        while stack:
            x, y = stack.pop()
            for point in ((x-1,y), (x+1,y), (x,y-1), (x,y+1)):
                if point in red:
                    red.remove(point); stack.append(point); component.append(point)
        if len(component) < 20:
            continue
        xs, ys = zip(*component)
        left, top, right, bottom = min(xs), min(ys), max(xs)+1, max(ys)+1
        if (.5 < (right-left)/(bottom-top) < 2 and max(right-left,bottom-top) > width*.025
                and height*.14 < (top+bottom)/2 < height*.45):
            noses.append((top, len(component), (left,top,right,bottom)))
    if not noses:
        raise ValueError(f"No stable nose landmark: {path.name}")
    largest = max(item[1] for item in noses)
    _, _, (left,top,right,bottom) = min(item for item in noses if item[1] >= largest*.2)
    nose_x, nose_y = (left+right)/2, (top+bottom)/2
    diameter = max(right-left,bottom-top)
    spans = []
    for y in range(max(0,int(nose_y-diameter*.3)), min(height,int(nose_y+diameter*1.1)), max(1,round(diameter*.1))):
        left = right = int(nose_x)
        while left > 0 and pixels[left-1,y][3] > 180: left -= 1
        while right < width-1 and pixels[right+1,y][3] > 180: right += 1
        spans.append((right-left+1,(left+right)/2))
    return {"size": [width,height], "nose": [nose_x,nose_y], "head": max(v[0] for v in spans), "headCenter": max(spans)[1],
            "bbox": image.getchannel("A").point(lambda v: 255 if v > 180 else 0).getbbox()}


def registration(root: Path, manifest: dict) -> tuple[dict, dict]:
    bases = {}
    for animation in manifest["animations"].values():
        for name in animation["frames"]:
            bases[name] = animation.get("baseFrame", name)
    metrics = {name: measure(root/name) for name in set(bases.values())}
    idle = manifest["animations"]["idle"]
    reference = metrics[idle.get("baseFrame", idle["frames"][0])]
    raw, union = {}, [float("inf"),float("inf"),-float("inf"),-float("inf")]
    for name, metric in metrics.items():
        scale = reference["head"]/metric["head"]
        x = reference["nose"][0]-metric["nose"][0]*scale
        y = reference["nose"][1]-metric["nose"][1]*scale
        raw[name] = [x,y,metric["size"][0]*scale,metric["size"][1]*scale]
        a,b,c,d = metric["bbox"]
        for index, value in enumerate((x+a*scale,y+b*scale,x+c*scale,y+d*scale)):
            union[index] = min(union[index],value) if index < 2 else max(union[index],value)
    canvas = reference["size"][0]
    fit = canvas*.94/max(union[2]-union[0],union[3]-union[1])
    offset_x = (canvas-(union[2]-union[0])*fit)/2-union[0]*fit
    offset_y = (canvas-(union[3]-union[1])*fit)/2-union[1]*fit
    rectangles = {name: [(raw[base][0]*fit+offset_x)/canvas,(raw[base][1]*fit+offset_y)/canvas,
                         raw[base][2]*fit/canvas,raw[base][3]*fit/canvas] for name,base in bases.items()}
    result = {"frames": rectangles, "headWidth": reference["head"]*fit/canvas, "anchor": [(reference["headCenter"]*fit+offset_x)/canvas,(reference["nose"][1]*fit+offset_y)/canvas]}
    report = {"frames": len(rectangles), "sourceHeadWidths": {name:m["head"] for name,m in metrics.items()},
              "registeredHeadWidth": reference["head"]*fit, "referenceCanvas": canvas}
    return result, report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("frames", type=Path)
    args = parser.parse_args()
    path = args.frames/"pet.json"
    manifest = json.loads(path.read_text())
    manifest["registration"], report = registration(args.frames,manifest)
    path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n")
    (args.frames.parent/"registration-report.json").write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps(report))
