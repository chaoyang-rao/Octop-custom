"""Integrate original shape/color avatars into the saved projects-v2 dashboard.

Only the active module graph is rebuilt. The baseline keeps the previous SSO,
project grouping and ACP customizations. New immutable names prevent mixed
application state modules when lazy chunks were already cached.
"""
from pathlib import Path
import hashlib
import json
import re
import runpy
import subprocess

from avatar_core_patch import once, patch_main, patch_messages, patch_navigation_avatar_css

ROOT = Path(__file__).resolve().parents[1]
if json.loads((ROOT.parent / 'scripts/custom/upstream-lock.json').read_text())['upstream_version'] != '1.0.2':
    raise SystemExit('Legacy 1.0.2 patcher: rebuild dashboard/ and run scripts/custom/sync_dashboard.py instead.')
BASE = ROOT / 'baselines' / 'projects-v2' / 'octop' / 'dashboard'
DASH = ROOT / 'packages' / 'octop' / 'dashboard'
ASSETS = DASH / 'assets'
SOURCE_RELEASE = 'projects-v2'
RELEASE = 'avatars-v60'
MAIN = 'index.BsYGCvv_.projects-v2.js'
EDIT = 'EditAgentDrawer.w674TDCV.projects-v2.js'
CREATE = 'index.Bxr_iAco.projects-v2.js'
MESSAGES = 'index.Bexwf9h5.projects-v2.js'
COMPOSER = 'index.G9_xhF8C.projects-v2.js'
NAV_CSS = 'index.Ds_DN6_-.projects-v2.css'












def patch_edit(s):
    s = 'import {createExpertAvatars} from "./expert-avatars.js";import {createAvatarSettings} from "./expert-avatar-integration.js";\n' + s
    s = once(s, 'function EditAgentDrawerBody(',
        'const expertAvatarUi=createExpertAvatars({React:reactExports}),ExpertAvatarSettings=createAvatarSettings({React:reactExports,avatars:expertAvatarUi});function EditAgentDrawerBody(')
    s = once(s, '[iconUrl,setIconUrl]=reactExports.useState(agent.icon_url),',
        '[iconUrl,setIconUrl]=reactExports.useState(agent.uploaded_icon_url??(agent.avatar_shape?null:agent.icon_url)),[avatarShape,setAvatarShape]=reactExports.useState(agent.avatar_shape??null),[avatarColor,setAvatarColor]=reactExports.useState(agent.avatar_color??"ink"),')
    s = once(s, 'setIconUrl(typeof ag.icon_url=="string"&&ag.icon_url.trim()?ag.icon_url:null);',
        'setIconUrl(ag.uploaded_icon_url??(ag.avatar_shape?null:ag.icon_url)??null),setAvatarShape(ag.avatar_shape??null),setAvatarColor(ag.avatar_color??"ink");')
    s = once(s, 'color:nextColor,config:nextConfig,',
        'color:nextColor,avatar_shape:avatarShape,avatar_color:avatarColor,config:nextConfig,')
    s = once(s, 'color:nextColor,icon_url:iconUrl}),onClose()',
        'color:nextColor,avatar_shape:avatarShape,avatar_color:avatarColor,uploaded_icon_url:iconUrl,icon_url:avatarShape?expertAvatarUi.avatarUrl(avatarShape,avatarColor):iconUrl}),onClose()')
    s = once(s, 'remote,colorPalette,form,iconUrl,onClose,',
        'remote,colorPalette,form,iconUrl,avatarShape,avatarColor,onClose,')
    s = once(s, 'setIconUrl(result.icon_url),await refresh(', 'setIconUrl(result.icon_url),setAvatarShape(null),await refresh(')
    s = once(s, 'setIconUrl(null),await refresh(', 'setIconUrl(null),await refresh(')

    start = s.index('jsxRuntimeExports.jsx(Form.Item,{label:t("experts.avatar"),children:')
    end = s.index('jsxRuntimeExports.jsx(Form.Item,{name:"is_shared"', start)
    old = s[start:end]
    avatar_start = old.index('jsxRuntimeExports.jsx(ExpertAvatarPicker,')
    color_start = old.index('jsxRuntimeExports.jsx(Form.Item,{label:t("experts.color")')
    # The original Form.Item closes as `}),`; preserve its existing upload
    # handlers and only move that child inside the new form adapter.
    upload = old[avatar_start:color_start]
    assert upload.endswith('}),')
    upload = upload[:-3]
    new = '''jsxRuntimeExports.jsx(Form.Item,{label:t("experts.avatar"),children:jsxRuntimeExports.jsx(ExpertAvatarSettings,{shape:avatarShape,color:avatarColor,onShapeChange:value=>setAvatarShape(value),onColorChange:value=>{setAvatarColor(value);setAvatarShape(prev=>prev||"blob")},disabled:avatarBusy||saving,imagePicker:''' + upload + ''',hasImage:!!iconUrl,onUseImage:()=>setAvatarShape(null)})}),'''
    s = s[:start] + new + s[end:]
    return s


def patch_create(s):
    s = 'import {createExpertAvatars} from "./expert-avatars.js";import {createAvatarSettings} from "./expert-avatar-integration.js";\n' + s
    s = once(s, 'function CreateFromExpertDrawer(',
        'const expertAvatarUi=createExpertAvatars({React:reactExports}),ExpertAvatarSettings=createAvatarSettings({React:reactExports,avatars:expertAvatarUi});function CreateFromExpertDrawer(')
    s = once(s, '[avatarFile,setAvatarFile]=reactExports.useState(null),',
        '[avatarShape,setAvatarShape]=reactExports.useState("blob"),[avatarColor,setAvatarColor]=reactExports.useState("ink"),[avatarFile,setAvatarFile]=reactExports.useState(null),')
    s = once(s, 'setColorPalette(parseStoredColor(defaults.color)??DEFAULT_PALETTE),setAvatarFile(null),',
        'setColorPalette(parseStoredColor(defaults.color)??DEFAULT_PALETTE),setAvatarShape(source.expert.avatar_shape??"blob"),setAvatarColor(source.expert.avatar_color??"ink"),setAvatarFile(null),')
    s = once(s, 'color:isCuratedPalette(colorPalette)?expertPaletteColor(colorPalette):colorPalette,...welcomeText?',
        'color:isCuratedPalette(colorPalette)?expertPaletteColor(colorPalette):colorPalette,avatar_shape:avatarShape,avatar_color:avatarColor,...welcomeText?')
    s = once(s, 'onPick:file=>{setAvatarFile(file),', 'onPick:file=>{setAvatarShape(null),setAvatarFile(file),')
    start = s.index('jsxRuntimeExports.jsx(Form.Item,{label:t("experts.avatar"),children:')
    end = s.index('jsxRuntimeExports.jsx(Form.Item,{name:"conversation_mode"', start)
    old = s[start:end]
    avatar_start = old.index('jsxRuntimeExports.jsx(ExpertAvatarPicker,')
    color_start = old.index('jsxRuntimeExports.jsx(Form.Item,{label:t("experts.color")')
    upload = old[avatar_start:color_start]
    assert upload.endswith('}),')
    upload = upload[:-3]
    clear_file = 'setAvatarFile(null);setAvatarPreview(prev=>(prev&&URL.revokeObjectURL(prev),null));'
    new = '''jsxRuntimeExports.jsx(Form.Item,{label:t("experts.avatar"),children:jsxRuntimeExports.jsx(ExpertAvatarSettings,{shape:avatarShape,color:avatarColor,onShapeChange:value=>{setAvatarShape(value);''' + clear_file + '''},onColorChange:value=>{setAvatarColor(value);setAvatarShape(prev=>prev||"blob");''' + clear_file + '''},disabled:submitting,imagePicker:''' + upload + ''',hasImage:!!avatarPreview||!!sourceIcon(source).iconUrl,onUseImage:()=>setAvatarShape(null)})}),'''
    s = s[:start] + new + s[end:]
    return s




patchers = {MAIN: patch_main, EDIT: patch_edit, CREATE: patch_create, MESSAGES: patch_messages, NAV_CSS: patch_navigation_avatar_css}
sources = {p.name: p.read_text(encoding='utf-8') for p in (BASE / 'assets').glob(f'*.{SOURCE_RELEASE}.*')
    if p.suffix in ('.js', '.css')}
if len(sources) != 217:
    raise RuntimeError(f'Unexpected active baseline graph size: {len(sources)}')
sources['project-folders.projects-v2.js'] = (ASSETS / 'project-folders.js').read_text(encoding='utf-8')
sources['project-folders.projects-v2.css'] = (ASSETS / 'project-folders.css').read_text(encoding='utf-8') + '\n' + (ASSETS / 'project-folder-picker.css').read_text(encoding='utf-8')
for name, patcher in patchers.items():
    sources[name] = patcher(sources[name])
account_patch = runpy.run_path(str(ROOT / 'frontend' / 'avatar_account_patch.py'))
account_settings_patch = runpy.run_path(str(ROOT / 'frontend' / 'account-avatar-settings-patch.py'))
sources[MAIN] = account_patch['patch_avatar_account_main'](sources[MAIN])
sources[MAIN] = account_settings_patch['patch_account_avatar_settings'](sources[MAIN])
sources[MESSAGES] = account_patch['patch_avatar_account_messages'](sources[MESSAGES])
compact_helper = ROOT / 'frontend' / 'compact-chat-patch.mjs'
sources[COMPOSER] = subprocess.run([
    'node', '--input-type=module', '-e',
    'import fs from "node:fs";import{pathToFileURL}from"node:url";const{patchCompactChatSource}=await import(pathToFileURL(process.argv[1]));process.stdout.write(patchCompactChatSource(fs.readFileSync(0,"utf8")));',
    str(compact_helper),
], input=sources[COMPOSER], capture_output=True, text=True, encoding='utf-8', check=True).stdout


def patch_chunk(name, helper, export_name):
    sources[name] = subprocess.run([
        'node', '--input-type=module', '-e',
        'import fs from "node:fs";import{pathToFileURL}from"node:url";const m=await import(pathToFileURL(process.argv[1]));process.stdout.write(m[process.argv[2]](fs.readFileSync(0,"utf8")));',
        str(ROOT / 'frontend' / helper), export_name,
    ], input=sources[name], capture_output=True, text=True, encoding='utf-8', check=True).stdout


patch_chunk(COMPOSER, 'voice-input-patch.mjs', 'patchVoiceInputSource')
for locale in ('en.CaWe8dRV.projects-v2.js', 'zh.D-7HvP3m.projects-v2.js'):
    patch_chunk(locale, 'voice-input-patch.mjs', 'patchVoiceLocaleSource')
patch_chunk(COMPOSER, 'model-shortcut-patch.mjs', 'patchComposerModelShortcut')
patch_chunk(COMPOSER, 'composer-files-patch.mjs', 'patchComposerFilesButton')
patch_chunk(COMPOSER, 'team-model-sticky-patch.mjs', 'patchTeamModelSticky')
for _locale, _fn in (('zh.D-7HvP3m.projects-v2.js', 'patchComposerFilesLocaleZh'), ('en.CaWe8dRV.projects-v2.js', 'patchComposerFilesLocaleEn')):
    patch_chunk(_locale, 'composer-files-patch.mjs', _fn)
patch_chunk('index.GTq9IEDq.projects-v2.js', 'token-usage-project-patch.mjs', 'patchTokenUsageProject')
patch_chunk('index.GTq9IEDq.projects-v2.js', 'token-usage-project-patch.mjs', 'patchTokenUsageSummaryProject')
patch_chunk('index.GTq9IEDq.projects-v2.js', 'token-usage-project-patch.mjs', 'patchTokenUsageDetailCard')
for locale in ('en.CaWe8dRV.projects-v2.js', 'zh.D-7HvP3m.projects-v2.js'):
    patch_chunk(locale, 'token-usage-project-patch.mjs', 'patchTokenUsageProjectLocale')
patch_chunk(MAIN, 'expert-status-patch.mjs', 'patchExpertStatusSource')
patch_chunk(MAIN, 'status-refresh-patch.mjs', 'patchSessionStatusPriority')
patch_chunk(EDIT, 'expert-status-patch.mjs', 'patchExpertManagementStatus')
patch_chunk(COMPOSER, 'status-refresh-patch.mjs', 'patchChatStatusPollingSource')
for locale in ('en.CaWe8dRV.projects-v2.js', 'zh.D-7HvP3m.projects-v2.js'):
    patch_chunk(locale, 'status-refresh-patch.mjs', 'patchExpertStatusLocaleSource')
patch_chunk(MAIN, 'team-experience-patch.mjs', 'patchExpertPresentation')
patch_chunk(CREATE, 'team-experience-patch.mjs', 'patchRandomAvatarCreate')
patch_chunk(EDIT, 'team-experience-patch.mjs', 'patchAvatarEdit')
patch_chunk(MESSAGES, 'team-experience-patch.mjs', 'patchManualProcessDetails')
patch_chunk(COMPOSER, 'team-experience-patch.mjs', 'patchProcessPreferenceMenu')
patch_chunk(COMPOSER, 'team-experience-patch.mjs', 'patchToolbarGlyphs')
for locale in ('en.CaWe8dRV.projects-v2.js', 'zh.D-7HvP3m.projects-v2.js'):
    patch_chunk(locale, 'team-experience-patch.mjs', 'patchExperienceLocale')
patch_chunk(MAIN, 'primary-team-patch.mjs', 'patchPrimaryTransport')
patch_chunk(MESSAGES, 'primary-team-patch.mjs', 'patchPrimarySpeakers')
patch_chunk(CREATE, 'primary-team-patch.mjs', 'patchPrimaryDrawer')
for locale in ('en.CaWe8dRV.projects-v2.js', 'zh.D-7HvP3m.projects-v2.js'):
    patch_chunk(locale, 'primary-team-patch.mjs', 'patchPrimaryLocale')
patch_chunk(EDIT, 'expert-reuse-patch.mjs', 'patchExpertReuse')
patch_chunk(CREATE, 'expert-reuse-patch.mjs', 'patchExpertReuseTable')
for locale in ('en.CaWe8dRV.projects-v2.js', 'zh.D-7HvP3m.projects-v2.js'):
    patch_chunk(locale, 'expert-reuse-patch.mjs', 'patchExpertReuseLocale')
subprocess.run(['node', str(ROOT / 'frontend' / 'build_user_pages.mjs')], check=True)
patch_chunk(MAIN, 'application-connectors-patch.mjs', 'patchApplicationChannels')
patch_chunk('AgentPluginsPanel.BJlhPlDN.projects-v2.js', 'application-connectors-patch.mjs', 'patchApplicationChannelForms')
patch_chunk('index.C1lMbskB.projects-v2.js', 'application-connectors-patch.mjs', 'patchApplicationConnectorCard')
for locale in ('en.CaWe8dRV.projects-v2.js', 'zh.D-7HvP3m.projects-v2.js'):
    patch_chunk(locale, 'application-connectors-patch.mjs', 'patchApplicationLocale')
patch_chunk(MAIN, 'user-pages-patch.mjs', 'patchUserPagesMain')
patch_chunk(MAIN, 'brand-mark-patch.mjs', 'patchBrandMark')
patch_chunk(MAIN, 'brand-mark-patch.mjs', 'patchBrandWordmark')
patch_chunk(MAIN, 'nav-icons-patch.mjs', 'patchNavIconsSource')
patch_chunk(MAIN, 'knowledge-import-url-patch.mjs', 'patchKnowledgeApiSource')
patch_chunk('index.DH7bXiZ0.projects-v2.js', 'knowledge-import-url-patch.mjs', 'patchKnowledgePageSource')
for locale in ('en.CaWe8dRV.projects-v2.js', 'zh.D-7HvP3m.projects-v2.js'):
    patch_chunk(locale, 'user-pages-patch.mjs', 'patchUserPagesLocale')
for locale in ('en.CaWe8dRV.projects-v2.js', 'zh.D-7HvP3m.projects-v2.js'):
    patch_chunk(locale, 'knowledge-import-url-patch.mjs', 'patchKnowledgeImportLocale')
extra_files = ('expert-avatars.js', 'expert-avatars.css', 'expert-avatar-integration.js', 'expert-avatar-integration.css',
               *account_patch['EXTRA_ASSETS'], 'compact-chat.css', 'sidebar-scrollbars.css', 'toolbar-contrast.css', 'project-folder-picker.js', 'model-shortcut.css', 'expert-work-status.js', 'expert-work-status.css', 'expert-presentation.js', 'expert-presentation.css', 'toolbar-glyphs.css', 'expert-reuse.js', 'nav-icons.js', 'user-features.pages.js', 'token-usage.css', 'composer-files.js', 'composer-files.css')
for name in extra_files:
    sources[name] = (ASSETS / name).read_text(encoding='utf-8')
mapping = {}
for name in sources:
    if name in ('sidebar-scrollbars.css', 'toolbar-contrast.css', 'model-shortcut.css', 'token-usage.css', 'composer-files.css', 'expert-work-status.css', 'expert-presentation.css', 'toolbar-glyphs.css'):
        mapping[name] = f'{Path(name).stem}.{hashlib.sha256(sources[name].encode()).hexdigest()[:10]}.css'
    else:
        mapping[name] = name.replace(f'.{SOURCE_RELEASE}.', f'.{RELEASE}.') if f'.{SOURCE_RELEASE}.' in name else f'{Path(name).stem}.{RELEASE}{Path(name).suffix}'
pattern = re.compile('|'.join(re.escape(name) for name in sorted(mapping, key=len, reverse=True)))
rewrite = lambda text: pattern.sub(lambda match: mapping[match.group()], text)
for name, content in sources.items():
    (ASSETS / mapping[name]).write_text(rewrite(content), encoding='utf-8', newline='\n')
html = (BASE / 'index.html').read_text(encoding='utf-8')
html = html.replace('</head>', '    <link rel="stylesheet" href="/assets/expert-avatars.css">\n    <link rel="stylesheet" href="/assets/expert-avatar-integration.css">\n  </head>')
for name in (*account_patch['STYLESHEETS'], 'compact-chat.css', 'sidebar-scrollbars.css', 'toolbar-contrast.css', 'model-shortcut.css', 'expert-work-status.css', 'expert-presentation.css', 'toolbar-glyphs.css', 'token-usage.css', 'composer-files.css'):
    html = html.replace('</head>', f'    <link rel="stylesheet" href="/assets/{name}">\n  </head>')
(DASH / 'index.html').write_text(rewrite(html), encoding='utf-8', newline='\n')
(DASH / 'sw.js').write_text(
    '/* Octop custom build: the desktop shell must always load the current bundle, so the\n'
    '   PWA precache worker is replaced by a stub that clears caches and unregisters. */\n'
    "self.addEventListener('install', () => self.skipWaiting());\n"
    "self.addEventListener('activate', (event) => {\n"
    '  event.waitUntil((async () => {\n'
    '    try {\n'
    '      const keys = await caches.keys();\n'
    '      await Promise.all(keys.map((key) => caches.delete(key)));\n'
    '    } catch (error) {}\n'
    '    await self.clients.claim();\n'
    '    try {\n'
    '      await self.registration.unregister();\n'
    '    } catch (error) {}\n'
    '  })());\n'
    '});\n',
    encoding='utf-8',
    newline='\n',
)
(ROOT / 'frontend' / 'avatar-asset-release.json').write_text(json.dumps({
    'release': RELEASE, 'main': mapping[MAIN], 'assets': list(mapping.values()),
    'additional_assets': [mapping[name] for name in extra_files],
    'baseline': BASE.relative_to(ROOT.parent).as_posix(), 'patched_modules': [mapping[name] for name in patchers],
    'baseline_main_sha256': hashlib.sha256((BASE / 'assets' / MAIN).read_bytes()).hexdigest(),
}, indent=2), encoding='utf-8', newline='\n')
print(f'Prepared {len(mapping)} versioned assets, entry {mapping[MAIN]}')

# Release names are immutable; keep only the validated current graph in packages.
from prune_assets import prune_assets

prune_assets(DASH, json.loads((ROOT / 'frontend' / 'avatar-asset-release.json').read_text()), apply=True)
