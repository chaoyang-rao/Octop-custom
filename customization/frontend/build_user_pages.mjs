/** Bundle new user surfaces against the preserved dashboard's React/UI contexts. */
import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..');
const require=createRequire(path.join(root,'dashboard/package.json'));
const {build,transformSync}=require('esbuild');
const base=path.join(root,'customization/baselines/projects-v2/octop/dashboard/assets');
const imports=new Map();
for(const file of fs.readdirSync(base).filter(name=>name.endsWith('.projects-v2.js'))){
 const source=fs.readFileSync(path.join(base,file),'utf8');
 for(const match of source.matchAll(/import\{([^}]+)\}from"(\.\/[^\"]+)"/g)){
  for(const part of match[1].split(',')){
   const [alias,local]=part.split(' as ');
   if(local&&!imports.has(local))imports.set(local,{alias,from:match[2]});
  }
 }
}
const asset=url=>'/assets/'+url.replace(/^\.\//,'');
function named(name){const entry=imports.get(name);if(!entry)throw new Error(`Missing preserved export: ${name}`);return `export{${entry.alias} as ${name}}from${JSON.stringify(asset(entry.from))};`;}
const reactNames=['Children','Component','Fragment','Profiler','PureComponent','StrictMode','Suspense','cloneElement','createContext','createElement','createFactory','createRef','forwardRef','isValidElement','lazy','memo','startTransition','useCallback','useContext','useDebugValue','useDeferredValue','useEffect','useId','useImperativeHandle','useInsertionEffect','useLayoutEffect','useMemo','useReducer','useRef','useState','useSyncExternalStore','useTransition','version'];
const react=`import{r as R}from"/assets/vendor-react.DWWhhpb4.projects-v2.js";export default R;export const{${reactNames.join(',')}}=R;`;
const antd='export{F as Table,L as List,U as Upload}from"/assets/vendor-antd.CTwSf1Lt.projects-v2.js";'+named('message')+[...imports.entries()].filter(([,entry])=>entry.from.includes('vendor-antd.')).map(([name,entry])=>`export{${entry.alias} as ${name}}from${JSON.stringify(asset(entry.from))};`).join('\n');
const shims={
 react,
 'react/jsx-runtime':'import{j as J}from"/assets/vendor-react.DWWhhpb4.projects-v2.js";export const{jsx,jsxs,Fragment}=J;',
 'react-i18next':named('useTranslation'),
 'react-router-dom':['useNavigate','useLocation','useParams','useSearchParams','Navigate','Link'].filter(name=>imports.has(name)).map(named).join('\n'),
 antd,
 AgentContext:named('useAgent'),
 useCurrentUser:named('useCurrentUser'),
 antdMessage:named('message'),
 PageShell:`export{P as default}from"/assets/PageShell.8ngNwS9L.projects-v2.js";`,
 i18n:`export{i as default}from"/assets/vendor-utils.Bxy7mX_Z.projects-v2.js";`,
};
const sourceShims=new Map([
 ['context/AgentContext.tsx','AgentContext'],['hooks/useCurrentUser.ts','useCurrentUser'],
 ['utils/antdMessage.ts','antdMessage'],['layouts/PageShell.tsx','PageShell'],['i18n.ts','i18n'],
].map(([name,shim])=>[path.join(root,'dashboard/src',name),shim]));
const nativeHelper=transformSync(fs.readFileSync(path.join(root,'dashboard/src/pages/Chat/utils/nativeCliPresentation.ts'),'utf8'),{loader:'ts',format:'esm',target:'es2022'}).code;
fs.writeFileSync(path.join(root,'customization/packages/octop/dashboard/assets/native-cli-presentation.js'),nativeHelper);
const report=await build({
 stdin:{contents:'import{useNotificationPresence}from"./pages/MobileAccess/useNotificationPresence";export function NotificationPresence(){useNotificationPresence();return null;}export{default as NativeCli}from"./pages/NativeCli";export{default as TaskQueue}from"./pages/TaskQueue";export{default as MobileAccess}from"./pages/MobileAccess";export{default as AccountConnections}from"./pages/AccountConnections";export{default as ConversationLibrary}from"./pages/ConversationLibrary";',resolveDir:path.join(root,'dashboard/src'),sourcefile:'user-features.entry.tsx',loader:'tsx'},
 outfile:path.join(root,'customization/packages/octop/dashboard/assets/user-features.pages.js'),
 bundle:true,format:'esm',platform:'browser',target:'es2022',jsx:'automatic',minify:true,metafile:true,
 define:{'process.env.NODE_ENV':'"production"'},
 plugins:[{name:'preserved-dashboard-contexts',setup(builder){
  builder.onResolve({filter:/.*/},async args=>{
   if(args.path.startsWith('/assets/'))return{path:args.path,external:true};
   if(Object.hasOwn(shims,args.path))return{path:args.path,namespace:'octop-shim'};
   if(args.path.startsWith('.')||args.path.startsWith('@/')||path.isAbsolute(args.path)){
    const candidate=args.path.startsWith('@/')?path.join(root,'dashboard/src',args.path.slice(2)):path.resolve(args.resolveDir,args.path);
    for(const suffix of ['', '.ts','.tsx','.mjs']){
     const shim=sourceShims.get(candidate+suffix);
     if(shim)return{path:shim,namespace:'octop-shim'};
    }
    if(args.path.startsWith('@/'))return builder.resolve(candidate,{kind:args.kind,resolveDir:args.resolveDir});
   }
  });
  builder.onLoad({filter:/.*/,namespace:'octop-shim'},args=>({contents:shims[args.path],loader:'js',resolveDir:root}));
 }}],
});
const bundled=Object.keys(report.metafile.inputs);
for(const blocked of ['node_modules/react/','node_modules/antd/','context/AgentContext.tsx','layouts/PageShell.tsx','src/i18n.ts']){
 if(bundled.some(input=>input.includes(blocked)))throw new Error(`Duplicated live context: ${blocked}`);
}
console.log(`Built user features: ${bundled.length} inputs; preserved React, UI, router, language and agent contexts.`);
