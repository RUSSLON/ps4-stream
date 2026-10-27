const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const {webcrypto}=require('crypto');
const base=__dirname+'/../extension/';
const records=[];
let listener;
const extensionURL='chrome-extension://abc/options.html';
const state={apiKey:'test-long-secret-key-123456',additionalSites:['extra-rezka.test']};
const chrome={
  runtime:{id:'abc',getURL:path=>'chrome-extension://abc/'+path,onMessage:{addListener:cb=>{listener=cb}},onInstalled:{addListener:()=>{}},onStartup:{addListener:()=>{}}},
  storage:{local:{get:async()=>state}},
  permissions:{contains:async()=>true,onRemoved:{addListener:()=>{}}},
  scripting:{getRegisteredContentScripts:async()=>[],registerContentScripts:async()=>{},unregisterContentScripts:async()=>{}}
};
const context={chrome,crypto:webcrypto,URL,Uint16Array,console,TextDecoder,AbortController,
  setTimeout,clearTimeout,fetch:async (url,opt)=>{
    records.push({url,body:JSON.parse(opt.body),auth:opt.headers.Authorization});
    return {ok:true,status:200,json:async()=>({ok:true,expires_in_seconds:600})};
  }};
context.importScripts=(file)=>vm.runInContext(fs.readFileSync(base+file,'utf8'),sandbox,{filename:file});
const sandbox=vm.createContext(context);
vm.runInContext(fs.readFileSync(base+'background.js','utf8'),sandbox,{filename:'background.js'});
async function message(type,url,media) {
  return new Promise(resolve=>listener({type,media},{id:'abc',url},resolve));
}
(async()=>{
  const media={title:'Test',quality:'720p',url:'https://cdn.test/movie.mp4',subtitles:[]};
  const test=await message('PS4_SEND','https://rezka-tv.org/films/movie.html',media);
  assert(test.ok);assert(/^\d{4}$/.test(test.pin));assert.equal(test.url,'https://ps4-stream.onrender.com/');
  assert.equal(records[0].body.pin,test.pin);assert.equal(records[0].url,'https://ps4-stream.onrender.com/api/launch');
  const extra=await message('PS4_SEND','https://extra-rezka.test/films/test.html',media);
  assert(extra.ok);
  const reject=await message('PS4_SEND','https://evil.example/test.html',media);
  assert.equal(reject.ok,false);
  const demo=await message('PS4_TEST',extensionURL);
  assert(demo.ok);
  console.log('Chrome background tests: OK');
})().catch(e=>{console.error(e);process.exit(1)});
