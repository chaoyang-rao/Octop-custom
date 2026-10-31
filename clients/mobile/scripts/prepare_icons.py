"""Package the repository's existing MIT Octop brand for native launchers."""
from pathlib import Path
import json
from PIL import Image

ROOT = Path(__file__).resolve().parents[3]
MOBILE = ROOT / "clients/mobile"
source = ROOT / "desktop/src/build/appicon-macos.png"
original = Image.open(source).convert("RGBA")
original = original.crop(original.getchannel("A").getbbox())
background = (255, 32, 40)


def icon(size: int) -> Image.Image:
    resized = original.resize((size, size), Image.Resampling.LANCZOS)
    result = Image.new("RGB", (size, size), background)
    result.paste(resized, mask=resized.getchannel("A"))
    return result


catalog = MOBILE / "ios/Resources/Assets.xcassets/AppIcon.appiconset"
catalog.mkdir(parents=True, exist_ok=True)
icon(1024).save(catalog / "AppIcon1024.png", optimize=True)
(catalog / "Contents.json").write_text(json.dumps({"images": [{"filename": "AppIcon1024.png", "idiom": "universal", "platform": "ios", "size": "1024x1024"}], "info": {"author": "xcode", "version": 1}}, indent=2) + "\n")
(catalog.parent / "Contents.json").write_text('{"info":{"author":"xcode","version":1}}\n')
for density, size in [("mdpi", 48), ("hdpi", 72), ("xhdpi", 96), ("xxhdpi", 144), ("xxxhdpi", 192)]:
    directory = MOBILE / "android/app/src/main/res" / ("mipmap-" + density)
    directory.mkdir(parents=True, exist_ok=True)
    icon(size).save(directory / "ic_launcher.png", optimize=True)
    icon(size).save(directory / "ic_launcher_round.png", optimize=True)
foreground = MOBILE / "android/app/src/main/res/drawable-nodpi"
foreground.mkdir(parents=True, exist_ok=True)
icon(432).save(foreground / "octop_brand.png", optimize=True)
print("Prepared native icons from desktop/src/build/appicon-macos.png")
