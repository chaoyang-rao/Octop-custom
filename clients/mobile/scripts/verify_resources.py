"""Read-only native resource coverage and launcher checks."""
from pathlib import Path
import json,re,xml.etree.ElementTree as ET
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
catalog=json.loads((ROOT/'localization/catalog.json').read_text())['strings']
for item in catalog.values():assert item.get('zh') and item.get('en')
for directory,pattern in [(ROOT/'ios/Sources',r'\bL\("([^"]+)"'),(ROOT/'android/app/src/main/java',r'NativeStrings.text\("([^"]+)"')]:
 for source in directory.rglob('*'):
  if source.suffix not in {'.swift','.java'}:continue
  for key in re.findall(pattern,source.read_text()):assert key in catalog,(source.name,key)
for lang,folder in [('en','values'),('zh','values-zh')]:
 resources=ET.parse(ROOT/f'android/app/src/main/res/{folder}/strings.xml').getroot()
 assert {value.attrib['name'] for value in resources}==set(catalog)
 with Image.open(ROOT/'ios/Resources/Assets.xcassets/AppIcon.appiconset/AppIcon1024.png') as icon:assert icon.size==(1024,1024) and icon.mode=='RGB'
for density,size in [('mdpi',48),('hdpi',72),('xhdpi',96),('xxhdpi',144),('xxxhdpi',192)]:
 for name in ['ic_launcher','ic_launcher_round']:
  with Image.open(ROOT/f'android/app/src/main/res/mipmap-{density}/{name}.png') as icon:assert icon.size==(size,size)
xml=(ROOT/'android/app/src/main/res/drawable/octop_launcher_foreground.xml').read_text()
assert '@mipmap/ic_launcher' not in xml and '@drawable/octop_brand' in xml
print(f'Native zh/en resources: {len(catalog)} keys covered; iOS opaque 1024 icon and Android 5 densities/adaptive icons verified')
