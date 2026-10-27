"use strict";
const SOURCES = ["hdrezka-fly.net", "hdrezka.ag", "rezka.ag", "rezka.fi"];
function allowedSender(sender) {
  try {
    const url = new URL(sender.url || sender.tab?.url || "");
    return url.protocol === "https:" && SOURCES.some(s => url.hostname === s || url.hostname.endsWith("." + s));
  } catch (_) {return false;}
}
function validRender(value) {
  try {
    const u = new URL(value);
    if (u.protocol !== 'https:' || !u.hostname.endsWith('.onrender.com') || u.username || u.password || u.pathname !== '/' || u.search || u.hash) return '';
    return u.origin;
  } catch (_) {return '';}
}
async function subtitleText(url) {
  const u = new URL(url);
  if (u.protocol !== 'https:') throw new Error('Нужен HTTPS');
  const permission = await chrome.permissions.contains({origins: ['https://*/*']});
  if (!permission) throw new Error('В настройках расширения включи доступ для субтитров');
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 12000);
  try {
    const response = await fetch(u.href, {credentials:'omit', signal: controller.signal, redirect:'error'});
    if (!response.ok) throw new Error('HTTP ' + response.status);
    if (Number(response.headers.get('content-length') || 0) > 750000) throw new Error('Файл слишком большой');
    const bytes = await response.arrayBuffer();
    if (bytes.byteLength > 750000) throw new Error('Файл слишком большой');
    let text = new TextDecoder('utf-8').decode(bytes);
    if (text.includes('\ufffd')) text = new TextDecoder('windows-1251').decode(bytes);
    if (!text.includes('-->')) throw new Error('Неверный формат SRT/VTT');
    return text;
  } finally {clearTimeout(timeout);}
}
async function send(media) {
  const config = await chrome.storage.local.get(['renderUrl','apiKey']);
  const origin = validRender(config.renderUrl || '');
  if (!origin || !config.apiKey) throw new Error('Сначала настрой адрес Render и API_KEY: нажми значок расширения Chrome.');
  if (!media || typeof media.url !== 'string' || !/^https?:\/\//i.test(media.url)) throw new Error('Некорректная ссылка на видео');
  const warnings = [];
  const out = {title: String(media.title || '').slice(0,180), quality: String(media.quality || '').slice(0,40), url:media.url, subtitles:[]};
  for (const s of (media.subtitles || []).slice(0,8)) {
    try {
      const t = await subtitleText(s.url);
      out.subtitles.push({lang:String(s.lang||'Субтитры').slice(0,80), text:t});
    } catch (e) { warnings.push('Субтитры ' + s.lang + ': ' + (e.message || String(e))); }
  }
  const response = await fetch(origin + '/api/launch', {
    method:'POST', headers:{'Content-Type':'application/json','Authorization':'Bearer '+config.apiKey},
    body: JSON.stringify(out), credentials:'omit'
  });
  const json = await response.json();
  if (!response.ok || !json.ok) throw new Error(json.error || 'Render вернул HTTP ' + response.status);
  return {...json, warnings};
}
chrome.runtime.onMessage.addListener((message, sender, respond) => {
  if (message?.type !== 'PS4_SEND') return false;
  if (!allowedSender(sender)) {respond({ok:false,error:'Неподдерживаемый сайт'});return false;}
  send(message.media).then(result => respond(result)).catch(e => respond({ok:false,error:e.message||String(e)}));
  return true;
});
