"""User-only name/image/preset selector patch, applied after avatar_account_patch.

No account preference is migrated. The explicit name option uses the existing
nullable avatar_icon API, whose complete user response updates account context.
"""


def _once(source, old, new):
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f'Expected one account settings patch point, found {count}: {old[:120]}')
    return source.replace(old, new, 1)


def patch_account_avatar_settings(source):
    start = source.index('function ProfileAvatarPicker(')
    end = source.index('const menuPopover=', start)
    picker = source[start:end]
    picker = _once(picker, 'function ProfileAvatarPicker({avatarUrl,icon:icon2,kind="user",',
        'function ProfileAvatarPicker({avatarUrl,icon:icon2,user,kind="user",')
    picker = _once(picker, 'presets=presetsFor(kind);',
        'presets=kind==="user"?[{id:"__account_name__",isName:!0,bg:"var(--fn-bg-secondary)",fg:"var(--fn-text-primary)"},...presetsFor(kind)]:presetsFor(kind);')
    old_preview = 'jsxRuntimeExports.jsx(ProfileAvatar,{url:displayUrl,icon:icon2,kind,className:[styles$i.profileAvatarPickerPreview,kind==="role"?styles$i.profileAvatarPickerPreviewRole:""].filter(Boolean).join(" ")})'
    picker = _once(picker, old_preview,
        '(kind==="user"?jsxRuntimeExports.jsx(AccountInitialAvatar,{user:{...user,display_name:(user==null?void 0:user.display_name)??(user==null?void 0:user.username)??"姓名",avatar_url:displayUrl,avatar_icon:icon2},className:styles$i.profileAvatarPickerPreview}):' + old_preview + ')')
    picker = _once(picker,
        'const selected=!hasPhoto&&(index===0?!icon2:icon2===preset.id),label2=t(index===0?"adminUsers.avatarDefault":preset.labelKey),',
        'const selected=!hasPhoto&&(kind==="user"?(preset.isName?!icon2:icon2===preset.id):(index===0?!icon2:icon2===preset.id)),label2=preset.isName?"无图片（显示姓名）":t(kind==="role"&&index===0?"adminUsers.avatarDefault":preset.labelKey),')
    picker = _once(picker, 'children:portrait?jsxRuntimeExports.jsx("img",{src:preset.src,alt:""}):PresetIcon?',
        'children:preset.isName?jsxRuntimeExports.jsx("span",{style:{fontSize:12,fontWeight:600},children:"姓名"}):portrait?jsxRuntimeExports.jsx("img",{src:preset.src,alt:""}):PresetIcon?')
    picker = _once(picker, 'children:t("experts.avatarHint")',
        'children:kind==="user"?t("account.avatarNameHint","可选 PNG、JPEG、WebP 或 GIF，不超过 5 MB。未设置图片或内置头像时显示姓名。"):t("experts.avatarHint")')
    picker = _once(picker, 'children:t("adminUsers.avatarSamples")',
        'children:kind==="user"?t("account.avatarChoices","头像选项"):t("adminUsers.avatarSamples")')
    source = source[:start] + picker + source[end:]

    # Only the current-account picker receives the real user's display name.
    # Role pickers and expert avatar settings retain their existing props.
    source = _once(source, 'ProfileAvatarPicker,{kind:"user",avatarUrl:user.avatar_url,icon:user.avatar_icon,',
        'ProfileAvatarPicker,{kind:"user",user,avatarUrl:user.avatar_url,icon:user.avatar_icon,')
    source = _once(source, 'children:t("account.avatarHint")',
        'children:t("account.avatarNameIntro","默认显示姓名，也可选择内置头像或上传自己的图片。")')
    source = _once(source,
        'onSelectIcon:async icon2=>{user&&(onUserChange==null||onUserChange({...user,avatar_icon:icon2,avatar_url:null}));try{onUserChange==null||onUserChange(await authApi.setAvatarIcon(icon2))}catch(err){throw message.error(apiErrorMessage(err,t("experts.avatarUploadFailed"),t)),err}},',
        'onSelectIcon:async icon2=>{user&&(onUserChange==null||onUserChange({...user,avatar_icon:icon2,avatar_url:null}));try{onUserChange==null||onUserChange(await authApi.setAvatarIcon(icon2))}catch(err){user&&(onUserChange==null||onUserChange(user));throw message.error(apiErrorMessage(err,t("experts.avatarUploadFailed"),t)),err}},')
    return source


patch_main = patch_account_avatar_settings
