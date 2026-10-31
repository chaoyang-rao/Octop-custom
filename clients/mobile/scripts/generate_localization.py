"""Generate native zh/en resources from the checked-in independent copy catalog."""
from pathlib import Path
import json,re
from xml.sax.saxutils import escape

ROOT=Path(__file__).resolve().parents[1]
strings=json.loads((ROOT/'localization/catalog.json').read_text())['strings']
for language in ['en','zh']:
 folder=ROOT/'ios/Resources'/(language+'.lproj');folder.mkdir(parents=True,exist_ok=True)
 def swift(value):
  value=re.sub(r'\{(\d+)\}',lambda m:'%'+str(int(m.group(1))+1)+'$@',value)
  return json.dumps(value,ensure_ascii=False)
 (folder/'Localizable.strings').write_text('\n'.join(json.dumps(key)+' = '+swift(value[language])+';' for key,value in sorted(strings.items()))+'\n')
 android=ROOT/'android/app/src/main/res'/('values' if language=='en' else 'values-zh');android.mkdir(parents=True,exist_ok=True)
 rows=['<resources>']
 for key,value in sorted(strings.items()):
  text=re.sub(r'\{(\d+)\}',lambda m:'%'+str(int(m.group(1))+1)+'$s',value[language])
  text=escape(text).replace("'", "\\'").replace('"','\\"')
  rows.append('  <string name="'+key+'">'+text+'</string>')
 rows.append('</resources>');(android/'strings.xml').write_text('\n'.join(rows)+'\n')
print('Generated zh/en native resources:',len(strings),'keys')
