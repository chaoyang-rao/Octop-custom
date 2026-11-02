/**
 * Composer: "files I sent" button on the right cluster of the input box.
 * Lists the agent workspace ``inbound/`` folder (where chat uploads land).
 */

function once(source, before, after) {
  const count = source.split(before).length - 1;
  if (count !== 1) {
    throw new Error(`Composer files patch expected one anchor, found ${count}: ${before.slice(0, 80)}`);
  }
  return source.replace(before, after);
}

export function patchComposerFilesButton(source) {
  if (source.includes('ComposerFilesButton')) throw new Error('Composer files patch was already applied');
  let out = 'import {createComposerFilesButton} from "./composer-files.js";\n' + source;
  // Module scope: must be declared before the actions row render function runs.
  const reactImport = 'from"./vendor-react.';
  const importAt = out.indexOf(reactImport);
  if (importAt < 0) throw new Error('React import anchor changed');
  const importEnd = out.indexOf(';', importAt) + 1;
  out = `${out.slice(0, importEnd)}const ComposerFilesButton=createComposerFilesButton({React:reactExports,Icon:Paperclip});${out.slice(importEnd)}`;
  // Lives in the message area's floating action column, not the composer.
  out = once(
    out,
    'jsxRuntimeExports.jsxs("div",{className:chatStyles.chatFloatActions,children:[',
    'jsxRuntimeExports.jsxs("div",{className:chatStyles.chatFloatActions,children:[jsxRuntimeExports.jsx(Tooltip,{title:t("chat.files.sent","我发过的文件"),mouseEnterDelay:.35,placement:"left",children:jsxRuntimeExports.jsx("span",{className:chatStyles.chatFloatBtnWrap,children:jsxRuntimeExports.jsx(ComposerFilesButton,{agentId:resolvedAgentId,threadId,t,floating:!0,buttonClassName:chatStyles.chatFloatBtn})})}),',
  );
  return out;
}

const LOCALE_STRINGS = [
  {
    anchor: ',"polish":{"tooltip":"AI 润色提示词"',
    insert:
      ',"files":{"sent":"我发过的文件","empty":"还没有发送过文件或链接","links":"链接","loading":"加载中…","loadFailed":"文件列表加载失败","noAgent":"请先选择智能体"}',
  },
  {
    anchor: ',"polish":{"tooltip":"Polish prompt with AI"',
    insert:
      ',"files":{"sent":"What I sent","empty":"No files or links sent yet","links":"Links","loading":"Loading…","loadFailed":"Could not load the file list","noAgent":"Pick an agent first"}',
  },
];

export function patchComposerFilesLocale(source, lang) {
  if (source.includes('"files":{"sent":')) throw new Error('Composer files locale patch was already applied');
  const entry = LOCALE_STRINGS.find(
    (candidate, index) =>
      source.includes(candidate.anchor) && ((index === 0) === (lang === 'zh')),
  );
  if (!entry) throw new Error('Composer files locale anchor changed');
  return once(source, entry.anchor, entry.insert + entry.anchor);
}

export function patchComposerFilesLocaleZh(source) {
  return patchComposerFilesLocale(source, 'zh');
}

export function patchComposerFilesLocaleEn(source) {
  return patchComposerFilesLocale(source, 'en');
}
