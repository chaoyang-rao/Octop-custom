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

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'baselines' / 'projects-v2' / 'octop' / 'dashboard'
DASH = ROOT / 'packages' / 'octop' / 'dashboard'
ASSETS = DASH / 'assets'
SOURCE_RELEASE = 'projects-v2'
RELEASE = 'avatars-v24'
MAIN = 'index.BsYGCvv_.projects-v2.js'
EDIT = 'EditAgentDrawer.w674TDCV.projects-v2.js'
CREATE = 'index.Bxr_iAco.projects-v2.js'
MESSAGES = 'index.Bexwf9h5.projects-v2.js'
COMPOSER = 'index.G9_xhF8C.projects-v2.js'
NAV_CSS = 'index.Ds_DN6_-.projects-v2.css'


def once(text, old, new):
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f'Expected 1 occurrence, got {count}: {old[:120]}')
    return text.replace(old, new, 1)


def patch_main(s):
    s = 'import {createExpertAvatars} from "./expert-avatars.js";\n' + s
    s = once(s, 'function ExpertIcon({iconUrl,iconName,size=22,className}){',
        'const expertAvatarUi=createExpertAvatars({React:reactExports});function ExpertIcon(props){const generated=expertAvatarUi.parseAvatarUrl(props.iconUrl);return generated?expertAvatarUi.renderAvatar({...generated,size:Math.ceil((props.size??22)*1.2),className:props.className,style:{maxWidth:"100%",maxHeight:"100%",flexShrink:0}}):jsxRuntimeExports.jsx(LegacyExpertIcon,props)}function LegacyExpertIcon({iconUrl,iconName,size=22,className}){')
    s = once(s, 'function ExpertAgentAvatar({iconName,iconUrl,color,iconSize:iconSize2,size=32,className,muted=!1}){',
        'function ExpertAgentAvatar(props){const generated=expertAvatarUi.parseAvatarUrl(props.iconUrl);return generated?expertAvatarUi.renderAvatar({...generated,size:Math.ceil((props.size??32)*1.2),className:props.className,style:{maxWidth:"100%",maxHeight:"100%",flexShrink:0}}):jsxRuntimeExports.jsx(LegacyExpertAgentAvatar,props)}function LegacyExpertAgentAvatar({iconName,iconUrl,color,iconSize:iconSize2,size=32,className,muted=!1}){')
    s = once(s, 'icon_url:agent.icon_url,color:agent.color,is_shared:',
        'icon_url:agent.icon_url,avatar_shape:agent.avatar_shape??null,avatar_color:agent.avatar_color??null,uploaded_icon_url:agent.uploaded_icon_url??null,color:agent.color,is_shared:')
    s = once(s, 'token:{borderRadius:10,...isMobile?{fontSize:15,fontSizeSM:13,fontSizeLG:17,fontSizeXL:22,controlHeight:36}:{}',
        'token:{borderRadius:10,fontSize:13,fontSizeSM:12,fontSizeLG:15,fontSizeXL:19,...isMobile?{fontSize:14,fontSizeSM:12,fontSizeLG:16,fontSizeXL:21,controlHeight:36}:{}')
    s = once(s, 'fontSize:typeSize(14,isMobile)', 'fontSize:typeSize(13,isMobile)')
    return patch_sidebar_scrollbars(patch_navigation_avatar_sizes(s))


def patch_sidebar_scrollbars(s):
    """Mark only the two otherwise unnamed global Dock scroll containers."""
    for old in (
        'jsxRuntimeExports.jsx("div",{style:{flex:1,minHeight:0,overflowY:isMinimal&&minimalPane==="records"?"hidden":"auto",overflowX:"hidden",display:"flex",flexDirection:"column"},children:navScrollBody})',
        'jsxRuntimeExports.jsx("div",{style:{flex:1,overflow:isMinimal&&minimalPane==="records"?"hidden":"auto",minHeight:0,display:"flex",flexDirection:"column"},children:navScrollBody})',
    ):
        s = once(s, old, old.replace('{style:', '{"data-octop-sidebar-scroll":"dock",style:', 1))
    return s


def patch_navigation_avatar_sizes(s):
    """Only the three shared avatar callsites in Experts / Teams / Cloud nav.

    Each tab uses ActiveAgentCard / InactiveAgentRow in the classic rail and
    MinimalAgentSessionNav in the compact rail. Keep chat/settings sizing alone.
    """
    for old in (
        'iconUrl:agent.icon_url,iconName:agent.icon_name,size:(_a=agent.icon_url)!=null&&_a.trim()?28:16',
        'iconUrl:agent.icon_url,iconName:agent.icon_name,size:(_a=agent.icon_url)!=null&&_a.trim()?26:14',
        'iconUrl:agent.icon_url,iconName:agent.icon_name,size:(_a=agent.icon_url)!=null&&_a.trim()?22:14',
    ):
        s = once(s, old, 'iconUrl:agent.icon_url,iconName:agent.icon_name,size:48')
    return s


def patch_navigation_avatar_css(s):
    """Enlarge the actual slots, not an image hidden inside its old 22px box."""
    changes = {
        '.index-module__agentCardAvatar__vcyg9{width:28px;height:28px;border-radius:50%;display:flex;align-items:center;justify-content:center;flex-shrink:0;overflow:hidden}':
        '.index-module__agentCardAvatar__vcyg9{width:48px;height:48px;border-radius:50%;display:flex;align-items:center;justify-content:center;flex-shrink:0;overflow:visible}',
        '.index-module__agentRowAvatar__RwSkb{width:26px;height:26px;border-radius:50%;display:flex;align-items:center;justify-content:center;flex-shrink:0;overflow:hidden}':
        '.index-module__agentRowAvatar__RwSkb{width:48px;height:48px;border-radius:50%;display:flex;align-items:center;justify-content:center;flex-shrink:0;overflow:visible}',
        '.index-module__minimalAgentIconSlot__x98C5{position:relative;width:22px;height:22px;flex-shrink:0}':
        '.index-module__minimalAgentIconSlot__x98C5{position:relative;width:48px;height:48px;flex-shrink:0}',
        '.index-module__minimalAgentAvatar__M4ZP0{position:absolute;top:0;right:0;bottom:0;left:0;border-radius:6px;display:inline-flex;align-items:center;justify-content:center;overflow:hidden;transition:opacity var(--fn-transition-fast)}':
        '.index-module__minimalAgentAvatar__M4ZP0{position:absolute;top:0;right:0;bottom:0;left:0;border-radius:6px;display:inline-flex;align-items:center;justify-content:center;overflow:visible;transition:opacity var(--fn-transition-fast)}',
        '.index-module__agentCardProfile__YJJO9{display:flex;align-items:flex-start;gap:8px;margin-bottom:4px;padding:4px 4px 2px}':
        '.index-module__agentCardProfile__YJJO9{display:flex;align-items:center;gap:8px;margin-bottom:4px;padding:4px 4px 2px}',
        '.index-module__agentRow__s5xUm{display:flex;align-items:flex-start;gap:8px;flex:1;min-width:0;padding:7px 8px;border:1px solid transparent;border-radius:10px;background:transparent;cursor:pointer;text-align:left;transition:background .15s,border-color .15s}':
        '.index-module__agentRow__s5xUm{display:flex;align-items:center;gap:8px;flex:1;min-width:0;padding:7px 8px;border:1px solid transparent;border-radius:10px;background:transparent;cursor:pointer;text-align:left;transition:background .15s,border-color .15s}',
        '.index-module__minimalAgentHeader__C9cuU{display:flex;align-items:center;gap:6px;width:100%;min-height:30px;padding-left:8px;border-radius:6px;transition:background var(--fn-transition-fast)}':
        '.index-module__minimalAgentHeader__C9cuU{display:flex;align-items:center;gap:6px;width:100%;min-height:56px;padding-left:8px;border-radius:6px;transition:background var(--fn-transition-fast)}',
    }
    for old, new in changes.items():
        s = once(s, old, new)
    return s


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


def patch_messages(s):
    s = 'import {createExpertAvatars} from "./expert-avatars.js";import {userBubblePresentation} from "./expert-avatar-integration.js";\n' + s
    s = once(s, 'function MessageBubble({',
        'const expertAvatarUi=createExpertAvatars({React:reactExports});function MessageBubble({')
    s = once(s, 'jsxRuntimeExports.jsxs("div",{className:chatStyles.userText,children:',
        'jsxRuntimeExports.jsxs("div",{className:chatStyles.userText,...userBubblePresentation(activeAgent,isTeamRoom,expertAvatarUi.bubbleStyle),children:')
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
patch_chunk(COMPOSER, 'native-composer-patch.mjs', 'patchNativeComposer')
for locale in ('en.CaWe8dRV.projects-v2.js', 'zh.D-7HvP3m.projects-v2.js'):
    patch_chunk(locale, 'user-pages-patch.mjs', 'patchUserPagesLocale')
extra_files = ('expert-avatars.js', 'expert-avatars.css', 'expert-avatar-integration.js', 'expert-avatar-integration.css',
               *account_patch['EXTRA_ASSETS'], 'compact-chat.css', 'sidebar-scrollbars.css', 'toolbar-contrast.css', 'project-folder-picker.js', 'model-shortcut.css', 'expert-work-status.js', 'expert-work-status.css', 'expert-presentation.js', 'expert-presentation.css', 'toolbar-glyphs.css', 'expert-reuse.js', 'user-features.pages.js', 'native-cli-presentation.js')
for name in extra_files:
    sources[name] = (ASSETS / name).read_text(encoding='utf-8')
mapping = {}
for name in sources:
    if name in ('sidebar-scrollbars.css', 'toolbar-contrast.css', 'model-shortcut.css', 'expert-work-status.css', 'expert-presentation.css', 'toolbar-glyphs.css'):
        mapping[name] = f'{Path(name).stem}.{hashlib.sha256(sources[name].encode()).hexdigest()[:10]}.css'
    else:
        mapping[name] = name.replace(f'.{SOURCE_RELEASE}.', f'.{RELEASE}.') if f'.{SOURCE_RELEASE}.' in name else f'{Path(name).stem}.{RELEASE}{Path(name).suffix}'
pattern = re.compile('|'.join(re.escape(name) for name in sorted(mapping, key=len, reverse=True)))
rewrite = lambda text: pattern.sub(lambda match: mapping[match.group()], text)
for name, content in sources.items():
    (ASSETS / mapping[name]).write_text(rewrite(content), encoding='utf-8', newline='\n')
html = (BASE / 'index.html').read_text(encoding='utf-8')
html = html.replace('</head>', '    <link rel="stylesheet" href="/assets/expert-avatars.css">\n    <link rel="stylesheet" href="/assets/expert-avatar-integration.css">\n  </head>')
for name in (*account_patch['STYLESHEETS'], 'compact-chat.css', 'sidebar-scrollbars.css', 'toolbar-contrast.css', 'model-shortcut.css', 'expert-work-status.css', 'expert-presentation.css', 'toolbar-glyphs.css'):
    html = html.replace('</head>', f'    <link rel="stylesheet" href="/assets/{name}">\n  </head>')
(DASH / 'index.html').write_text(rewrite(html), encoding='utf-8', newline='\n')
(DASH / 'sw.js').write_text(f'/* Expert avatars release {RELEASE}, shell {hashlib.sha256(rewrite(html).encode()).hexdigest()[:10]}. */\n' + rewrite((BASE / 'sw.js').read_text(encoding='utf-8')), encoding='utf-8', newline='\n')
(ROOT / 'frontend' / 'avatar-asset-release.json').write_text(json.dumps({
    'release': RELEASE, 'main': mapping[MAIN], 'assets': list(mapping.values()),
    'additional_assets': [mapping[name] for name in extra_files],
    'baseline': BASE.relative_to(ROOT.parent).as_posix(), 'patched_modules': [mapping[name] for name in patchers],
    'baseline_main_sha256': hashlib.sha256((BASE / 'assets' / MAIN).read_bytes()).hexdigest(),
}, indent=2), encoding='utf-8', newline='\n')
print(f'Prepared {len(mapping)} versioned assets, entry {mapping[MAIN]}')
