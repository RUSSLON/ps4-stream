const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const source = fs.readFileSync(__dirname+'/../extension/adapter.js','utf8');
const context = {window:{}, atob:x=>Buffer.from(x,'base64').toString('binary'), URL};
vm.runInNewContext(source, context);
const a = context.window.PS4RezkaAdapter;
const list = a.parseQualities('[1080p]https://cdn.example.com/1080.mp4,[720p]https://cdn.example.com/720.mp4');
assert.equal(list.length, 2); assert.equal(list[0].quality, '1080p');
const b64 = Buffer.from('[480p]https://cdn.example.com/480.mp4','utf8').toString('base64');
assert.equal(a.parseQualities('#h'+b64)[0].quality,'480p');
const subs=a.parseSubtitles('[Русский]https://cdn.example.com/r.srt,[English]https://cdn.example.com/e.vtt');
assert.equal(subs.length,2);
const helper=a.fromHelperLinks([
 {label:'720p',url:'https://cdn.example.org/a.mp4?token=xyz',isSubtitle:false},
 {label:'1080p',url:'https://cdn.example.org/b.mp4',isSubtitle:false},
 {label:'1080p',url:'https://cdn.example.org/b.mp4',isSubtitle:false},
 {label:'Русский',url:'https://static.example.org/rus.vtt',isSubtitle:true},
 {label:'bad',url:'javascript:alert(1)',isSubtitle:false}
]);
assert.equal(helper.videos.length,2);
assert.equal(helper.videos[0].quality,'1080p');
assert.equal(helper.subtitles[0].lang,'Русский');
console.log('Adapter tests: OK');
