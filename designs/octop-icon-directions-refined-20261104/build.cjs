const esbuild=require('../../dashboard/node_modules/esbuild');
const fs=require('node:fs');
const path=require('node:path');
const base=__dirname;
esbuild.buildSync({entryPoints:[path.join(base,'source/preview.jsx')],bundle:true,outfile:path.join(base,'preview.js'),nodePaths:[path.resolve(base,'../../dashboard/node_modules')],minify:true,define:{'process.env.NODE_ENV':'"production"'}});
const js=fs.readFileSync(path.join(base,'preview.js'),'utf8').replace(/<\/script/gi,'<\\/script');
const css=fs.readFileSync(path.join(base,'preview.css'),'utf8');
for(const family of ['a','b','c'])fs.writeFileSync(path.join(base,`option-${family}.html`),`<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Octop · 方案 ${family.toUpperCase()}</title><style>${css}</style></head><body data-family="${family}"><div id="root"></div><script>${js}</script></body></html>`);
