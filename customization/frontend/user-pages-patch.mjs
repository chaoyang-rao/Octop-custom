import fs from 'node:fs';

function once(source, from, to) {
 const count=source.split(from).length-1;
 if(count!==1)throw new Error(`User pages patch expected one anchor, got ${count}: ${from.slice(0,100)}`);
 return source.replace(from,to);
}
export function patchUserPagesMain(source){
 const declarations='const NativeCliExtension=reactExports.lazy(()=>import("./user-features.pages.js").then(m=>({default:m.NativeCli}))),NotificationPresenceExtension=reactExports.lazy(()=>import("./user-features.pages.js").then(m=>({default:m.NotificationPresence}))),TaskQueueExtension=reactExports.lazy(()=>import("./user-features.pages.js").then(m=>({default:m.TaskQueue}))),AccountConnectionsExtension=reactExports.lazy(()=>import("./user-features.pages.js").then(m=>({default:m.AccountConnections}))),MobileAccessExtension=reactExports.lazy(()=>import("./user-features.pages.js").then(m=>({default:m.MobileAccess}))),ConversationsExtension=reactExports.lazy(()=>import("./user-features.pages.js").then(m=>({default:m.ConversationLibrary})));\n';
 source=declarations+source;
 source=once(source,'SIDEBAR_NAV_KEYS=["chat","experts","tasks",','SIDEBAR_NAV_KEYS=["chat","conversations","experts","tasks","task-queue","account-connections","mobile-access","native-cli",');
 source=once(source,'SIDEBAR_GROUPED_NAV_KEYS=["personalization",','SIDEBAR_GROUPED_NAV_KEYS=["native-cli","account-connections","mobile-access","personalization",');
 source=once(source,'const pathToKey={','const pathToKey={"/conversations":"conversations","/task-queue":"task-queue","/account-connections":"account-connections","/mobile-access":"mobile-access","/native-cli":"native-cli",');
 source=once(source,'routeConfigs=[','routeConfigs=[{path:"/conversations",element:jsxRuntimeExports.jsx(ConversationsExtension,{})},{path:"/native-cli",element:jsxRuntimeExports.jsx(NativeCliExtension,{})},{path:"/task-queue",element:jsxRuntimeExports.jsx(TaskQueueExtension,{})},{path:"/account-connections",element:jsxRuntimeExports.jsx(AccountConnectionsExtension,{})},{path:"/mobile-access",element:jsxRuntimeExports.jsx(MobileAccessExtension,{})},');
 source=once(source,'function pathPermissionKeys(pathname){','function legacyPathPermissionKeys(pathname){');
 source=once(source,'function buildNavSections(user,opts){','function buildLegacyNavSections(user,opts){');
 source+='\nfunction pathPermissionKeys(pathname){if(pathname==="/conversations")return null;if(pathname==="/native-cli")return"admin";if(pathname==="/task-queue")return["tasks"];if(pathname==="/account-connections")return["connectors"];if(pathname==="/mobile-access")return null;return legacyPathPermissionKeys(pathname)}\n';
 source+='function buildNavSections(user,opts){const sections=buildLegacyNavSections(user,opts),top=sections[0]?.items,settings=sections.find(s=>s.id==="settings")?.items;if(top){const chat=top.find(item=>item.key==="chat");if(chat)top.splice(top.indexOf(chat)+1,0,{...chat,key:"conversations",path:"/conversations",labelKey:"nav.conversations"});const task=top.find(item=>item.key==="tasks");if(task)top.splice(top.indexOf(task)+1,0,{...task,key:"task-queue",path:"/task-queue",labelKey:"nav.taskQueue"})}if(settings){const connector=settings.find(item=>item.key==="connectors"),bridge=settings.find(item=>item.key==="bridge");if(connector)settings.splice(settings.indexOf(connector)+1,0,{...connector,key:"account-connections",path:"/account-connections",labelKey:"nav.accountConnections"});if(bridge)settings.push({...bridge,key:"mobile-access",path:"/mobile-access",labelKey:"nav.mobileAccess"})}const control=sections.find(s=>s.id==="control")?.items,acp=control?.find(item=>item.key==="acp");if(acp)control.splice(control.indexOf(acp)+1,0,{...acp,key:"native-cli",path:"/native-cli",labelKey:"nav.nativeCli"});return sections}\n';
 source=once(source,'a.default_model===b.default_model&&','a.default_model===b.default_model&&JSON.stringify(a.config?.native_cli)===JSON.stringify(b.config?.native_cli)&&');
 source=once(source,'jsxRuntimeExports.jsx(PwaUpdatePrompt,{}),','jsxRuntimeExports.jsx(reactExports.Suspense,{fallback:null,children:jsxRuntimeExports.jsx(NotificationPresenceExtension,{})}),jsxRuntimeExports.jsx(PwaUpdatePrompt,{}),');
 return source;
}
export function patchUserPagesLocale(source){
 const matched=source.match(/\b(zh|en) as default\b/);
 if(!matched)throw new Error('Locale default export changed');
 const locale=matched[1];
 const translations=JSON.parse(fs.readFileSync(new URL(`../../dashboard/src/locales/${locale}.json`,import.meta.url),'utf8'));
 const namespaces={};
 for(const key of ['taskQueue','mobileAccess','accountConnections','nativeCli','conversationLibrary']){
  if(!translations[key])throw new Error(`Missing user feature locale ${key}`);
  namespaces[key]=translations[key];
 }
 const nav=Object.fromEntries(['taskQueue','mobileAccess','accountConnections','nativeCli','conversations'].map(key=>[key,translations.nav[key]]));
 const pos=source.lastIndexOf('export{');
 if(pos<0)throw new Error('Locale exports changed');
 return source.slice(0,pos)+`Object.assign(${locale},${JSON.stringify(namespaces)});Object.assign(nav,${JSON.stringify(nav)});`+source.slice(pos);
}
