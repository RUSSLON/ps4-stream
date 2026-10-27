(() => {
  "use strict";
  if (document.getElementById("ps4stream-open")) return;
  if (!/(\.html|\/\d+)(?:$|[?#])/.test(location.pathname + location.search + location.hash)) return;
  let modal;
  const el = (name, className, text) => { const node=document.createElement(name); if(className)node.className=className; if(text)node.textContent=text; return node; };
  const say = (message, isError=false) => {
    const old=modal?.querySelector(".ps4-feedback"); if(old) old.remove();
    const node=el("div", "ps4-feedback"+(isError?" error":""), message);
    modal?.querySelector(".ps4-panel")?.appendChild(node);
  };
  function closeModal() { modal?.remove(); modal=null; }
  function makeModal() {
    closeModal();
    modal=el("div"); modal.id="ps4stream-modal";
    const panel=el("div","ps4-panel");
    const close=el("button","ps4-close","×"); close.type="button"; close.onclick=closeModal;
    panel.append(close,el("div","ps4-kicker","PlayStation streaming"),el("h2","","Отправить на PS4"),el("p","","Выбираем качество и субтитры. Потом открой адрес на консоли."));
    modal.appendChild(panel); panel.appendChild(close);
    modal.addEventListener("click", e => {if(e.target===modal)closeModal();});
    document.body.appendChild(modal);
    return panel;
  }
  async function openMenu() {
    const panel=makeModal(); say("Получаем доступные ссылки с сайта…");
    let info;
    try {info=await window.PS4RezkaAdapter.getSources();}
    catch(e) {say(e.message||String(e),true);return;}
    if(!modal)return;
    modal.querySelector(".ps4-feedback")?.remove();
    panel.querySelector("h2").textContent=info.title||"Отправить на PS4";
    panel.appendChild(el("div","ps4-section","КАЧЕСТВО ВИДЕО"));
    const radios=el("div");
    info.videos.forEach((video,i)=>{
      const line=el("label","ps4-option");const radio=el("input");radio.type="radio";radio.name="ps4-video";radio.value=String(i);radio.checked=i===0;
      line.append(radio,document.createTextNode(video.quality));radios.appendChild(line);
    });
    panel.appendChild(radios);
    const checkboxes=[];
    panel.appendChild(el("div","ps4-section","СУБТИТРЫ"));
    if(info.subtitles.length===0)panel.appendChild(el("p","","На этой странице субтитры не обнаружены."));
    for(const sub of info.subtitles){
      const line=el("label","ps4-option");const check=el("input");check.type="checkbox";
      line.append(check,document.createTextNode(sub.lang));panel.appendChild(line);checkboxes.push({check,sub});
    }
    const submit=el("button","ps4-submit","Отправить → PS4");
    panel.appendChild(submit);
    submit.onclick=async()=>{
      submit.disabled=true;submit.textContent="Отправляем на Render…";
      const idx=Number(panel.querySelector("input[name='ps4-video']:checked")?.value||0);
      const media={title:info.title,quality:info.videos[idx].quality,url:info.videos[idx].url,sourcePage:info.sourcePage,subtitles:checkboxes.filter(x=>x.check.checked).map(x=>x.sub)};
      try {
        const result=await chrome.runtime.sendMessage({type:"PS4_SEND",media});
        if(!result?.ok)throw Error(result?.error||"Неизвестная ошибка");
        say("Готово! Открой персональную ссылку на PS4. Сессия доступна 10 минут." + (result.warnings?.length ? " Внимание: " + result.warnings.join("; ") : ""));
        const link=el("a", "ps4-share", result.url);
        link.href=result.url; link.target="_blank"; link.rel="noopener noreferrer";
        link.style.display="block";link.style.overflowWrap="anywhere";link.style.padding="12px 0";
        panel.appendChild(link);
        const copy=el("button", "ps4-submit", "Скопировать ссылку");
        copy.onclick=async()=>{try{await navigator.clipboard.writeText(result.url); copy.textContent="Скопировано ✓";}catch(_){copy.textContent=result.url;}};
        panel.appendChild(copy);
        submit.textContent="Отправлено ✓";
      }catch(e){say(e.message||String(e),true);submit.textContent="Повторить отправку";submit.disabled=false;}
    };
  }
  const button=el("button","","▣ to PS4");button.type="button";button.id="ps4stream-open";
  button.addEventListener("click",openMenu);
  const helper=[...document.querySelectorAll("button, a, div")].find(node=>node.childElementCount<4 && /hdrezka\s*helper/i.test(node.textContent||"") && node.getBoundingClientRect().width>25 && node.getBoundingClientRect().width<320);
  if(helper && helper.parentElement && helper.parentElement!==document.body){helper.insertAdjacentElement("afterend",button);button.style.marginLeft="10px";}
  else{button.classList.add("ps4-float");document.body.appendChild(button);}
})();
