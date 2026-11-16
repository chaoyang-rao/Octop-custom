const test = require("node:test");
const assert = require("node:assert/strict");
const {mcpPath,allowedRequest} = require("./negative_ingress.cjs");
function request(url,ip,headers={}) {return {url,socket:{remoteAddress:ip},headers};}
test("only the gateway and local diagnostics reach MCP, including encoded and mixed-case paths",()=>{
 for(const path of ["/mcp","/mcp/","/MCP","/%6dcp","//mcp","/mcp?x=1"]){assert.equal(mcpPath(path),true);assert.equal(allowedRequest(request(path,"8.8.8.8")),false);assert.equal(allowedRequest(request(path,"::ffff:120.79.0.171")),true);}
});
test("forwarded source headers cannot turn a public proxy into a loopback MCP caller",()=>{
 for(const name of ["forwarded","x-forwarded-for","x-real-ip"]){assert.equal(allowedRequest(request("/mcp","127.0.0.1",{[name]:"120.79.0.171"})),false);assert.equal(allowedRequest(request("/mcp","8.8.8.8",{[name]:"120.79.0.171"})),false);}
});
test("ordinary business application requests are unchanged",()=>{
 for(const path of ["/","/api/overview","/assets/main.js","/health"]){assert.equal(allowedRequest(request(path,"8.8.8.8",{"x-forwarded-for":"8.8.8.8"})),true);}
});
