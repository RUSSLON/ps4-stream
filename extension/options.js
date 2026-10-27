'use strict';
const url = document.getElementById('renderUrl'), key = document.getElementById('apiKey'), status = document.getElementById('status');
chrome.storage.local.get(['renderUrl','apiKey']).then(x=>{url.value=x.renderUrl||'';key.value=x.apiKey||''});
document.getElementById('save').onclick = async () => {
  try {
    const u = new URL(url.value.trim());
    if(u.protocol !== 'https:' || !u.hostname.endsWith('.onrender.com') || u.pathname !== '/' || u.search || u.hash || u.username || u.password) throw Error('Укажи только адрес https://имя.onrender.com');
    if(key.value.trim().length < 12) throw Error('Слишком короткий API_KEY');
    await chrome.storage.local.set({renderUrl:u.origin, apiKey:key.value.trim()});
    status.textContent='✓ Настройки сохранены';
  }catch(e){status.textContent=e.message;}
};
document.getElementById('permission').onclick = async () => {
  const ok = await chrome.permissions.request({origins:['https://*/*']});
  status.textContent = ok ? '✓ Доступ для субтитров разрешён' : 'Разрешение не предоставлено';
};

document.getElementById('test').onclick = async () => {
  const link = document.getElementById('testLink');
  link.textContent = ''; link.removeAttribute('href');
  status.textContent = 'Отправляем демо на Render…';
  try {
    const conf = await chrome.storage.local.get(['renderUrl','apiKey']);
    if (!conf.renderUrl || !conf.apiKey) throw Error('Сначала сохрани адрес Render и API_KEY');
    const response = await fetch(conf.renderUrl + '/api/launch', {
      method:'POST', headers:{'Content-Type':'application/json','Authorization':'Bearer '+conf.apiKey},
      body:JSON.stringify({title:'Демо · Цветы (MDN)', quality:'MP4',url:'https://interactive-examples.mdn.mozilla.net/media/cc0-videos/flower.mp4',subtitles:[]}),
      credentials:'omit'
    });
    const result = await response.json();
    if (!response.ok || !result.ok) throw Error(result.error || 'Render: HTTP ' + response.status);
    status.textContent = '✓ Демо отправлено. Открой на PS4:';
    link.textContent = result.url; link.href = result.url;
  } catch(e) {status.textContent = e.message || String(e);}
};
