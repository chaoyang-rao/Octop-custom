/**
 * Knowledge base: import an online document (Feishu first) from a URL.
 *
 * Two production touch points:
 *  1. shell chunk — add `importDocumentUrl` to `knowledgeBasesApi`
 *  2. knowledge page chunk — add the toolbar button + confirm dialog
 * plus the two locale chunks for the new strings.
 */

function once(source, before, after) {
  const count = source.split(before).length - 1;
  if (count !== 1) {
    throw new Error(`Knowledge import patch expected one anchor, found ${count}: ${before.slice(0, 90)}`);
  }
  return source.replace(before, after);
}

export function patchKnowledgeApiSource(source) {
  if (source.includes('importDocumentUrl')) throw new Error('Knowledge import api patch was already applied');
  return once(
    source,
    'uploadDocument:(id,file,relativePath,onProgress)=>{',
    'importDocumentUrl:(id,url)=>request(`/knowledge-bases/${id}/documents/import-url`,{method:"POST",body:JSON.stringify({url})}),uploadDocument:(id,file,relativePath,onProgress)=>{',
  );
}

const HANDLER = 'const openImportUrl=()=>{const urlRef=reactExports.createRef();modal.confirm({title:t("knowledgeBases.importUrlTitle"),width:520,content:jsxRuntimeExports.jsxs("div",{style:{display:"flex",flexDirection:"column",gap:8},children:[jsxRuntimeExports.jsx(Input,{ref:urlRef,allowClear:!0,autoFocus:!0,placeholder:t("knowledgeBases.importUrlPlaceholder")}),jsxRuntimeExports.jsx("span",{style:{fontSize:12,color:"var(--fn-text-tertiary)"},children:t("knowledgeBases.importUrlHelp")})]}),okText:t("knowledgeBases.importUrl"),onOk:async()=>{const url=(urlRef.current?.input?.value||"").trim();if(!url)return message.warning(t("knowledgeBases.importUrlEmpty")),Promise.reject();try{await knowledgeBasesApi.importDocumentUrl(selected.id,url),message.success(t("knowledgeBases.importUrlDone")),await loadDetail(selected.id,{silent:!0})}catch(error){message.error(apiErrorMessage(error,t("knowledgeBases.importUrlFailed"),t));return Promise.reject()}}})};';

const BUTTON = 'canWriteSelected?jsxRuntimeExports.jsx(Button,{onClick:openImportUrl,children:t("knowledgeBases.importUrl")}):null,';

const RETURN_ANCHOR = 'return jsxRuntimeExports.jsxs(PageShell,{title:t("knowledgeBases.title")';

export function patchKnowledgePageSource(source) {
  if (source.includes('knowledgeBases.importUrl')) throw new Error('Knowledge import page patch was already applied');
  let out = once(
    source,
    'canWriteSelected?jsxRuntimeExports.jsx(Button,{type:"primary",icon:jsxRuntimeExports.jsx(FileUp,{size:14})',
    BUTTON + 'canWriteSelected?jsxRuntimeExports.jsx(Button,{type:"primary",icon:jsxRuntimeExports.jsx(FileUp,{size:14})',
  );
  return once(out, RETURN_ANCHOR, HANDLER + RETURN_ANCHOR);
}

const LOCALE_STRINGS = [
  {
    anchor: 'createFolder:"新建文件夹",createFolderFailed:"创建文件夹失败",',
    insert: 'importUrl:"从链接导入",importUrlTitle:"从链接导入在线文档",importUrlPlaceholder:"粘贴飞书文档链接，例如 https://xxx.feishu.cn/docx/…",importUrlHelp:"优先支持飞书云文档（docx / wiki）；其他 http(s) 网页会按正文提取。",importUrlDone:"已导入，正在建立索引",importUrlFailed:"导入失败",importUrlEmpty:"请先填写文档链接",',
  },
  {
    anchor: 'createFolder:"New folder",createFolderFailed:"Failed to create folder",',
    insert: 'importUrl:"Import from link",importUrlTitle:"Import an online document",importUrlPlaceholder:"Paste a Feishu doc link, e.g. https://xxx.feishu.cn/docx/…",importUrlHelp:"Feishu docs (docx / wiki) are fetched first; other http(s) pages are reduced to their text.",importUrlDone:"Imported — indexing started",importUrlFailed:"Import failed",importUrlEmpty:"Enter a document link first",',
  },
];

export function patchKnowledgeImportLocale(source) {
  if (source.includes('importUrl:"')) throw new Error('Knowledge import locale patch was already applied');
  const entry = LOCALE_STRINGS.find((candidate) => source.includes(candidate.anchor));
  if (!entry) throw new Error('Knowledge import locale anchor changed');
  return once(source, entry.anchor, entry.anchor + entry.insert);
}
