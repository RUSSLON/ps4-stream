/*
 * Rezka adapter. Uses same-site get_cdn_series metadata used by video helpers.
 * Prototype, independently implemented; not a bundled copy of HDrezka Helper.
 * Intentionally does NOT circumvent DRM, login or access controls.
 */
(() => {
  "use strict";
  const SALTS = ["IyMjI14hISMjIUBA", "QEBAQEAhIyMhXl5e", "JCQhIUAkJEBeIUAjJCRA", "JCQjISFAIyFAIyM=", "Xl5eIUAjIyEhIyM="];
  const RE_URL = /^https?:\/\//i;

  function decodeUrl(value) {
    if (typeof value !== "string") return "";
    if (/^(?:\[|https?:)/i.test(value)) return value;
    let result = value.replace(/^#h/, "");
    for (let i = 0; i < 60; i++) {
      const pos = result.indexOf("//_//");
      if (pos < 0) break;
      const after = result.slice(pos + 5);
      const salt = SALTS.find(s => after.startsWith(s));
      result = result.slice(0, pos) + after.slice(salt ? salt.length : 16);
    }
    try {
      // Decode Unicode-safe, as older response formats were base64-encoded.
      return atob(result);
    } catch (_) { return value; }
  }

  function cleanUrl(value) {
    if (!value) return "";
    let str = value.trim().replace(/\\\//g, "/");
    // Variants in a Rezka playlist can include :hls/:dash suffixes.
    str = str.split(/:hls|:dash|:m3u8/i)[0].trim();
    const first = str.match(/https?:\/\/[^\s,|;]+/i);
    if (!first) return "";
    str = first[0];
    try {
      const url = new URL(str);
      if (!RE_URL.test(url.href) || !["http:", "https:"].includes(url.protocol)) return "";
      return url.href;
    } catch (_) { return ""; }
  }

  function parseQualities(encoded) {
    const decoded = decodeUrl(encoded).replace(/<[^>]*>/g, "");
    const results = [];
    const qualityReg = /\[([^\]]+)\]([\s\S]*?)(?=\[[^\]]+\]|$)/g;
    let match;
    while ((match = qualityReg.exec(decoded))) {
      const value = match[2].split(/\s+or\s+|\s*\|\s*|,/i);
      const candidates = value.map(cleanUrl).filter(Boolean);
      const playable = candidates.find(u => /\.mp4(?:[?#]|$)/i.test(u)) || candidates.find(u => !/\.m3u8(?:[?#]|$)/i.test(u));
      if (playable) results.push({quality: match[1].trim(), url: playable});
    }
    if (!results.length) {
      const u = cleanUrl(decoded);
      if (u && !/\.m3u8(?:[?#]|$)/i.test(u)) results.push({quality: "Авто", url: u});
    }
    const seen = new Set();
    return results.filter(x => {
      const k = x.quality + "|" + x.url;
      if (seen.has(k)) return false;
      seen.add(k);
      return true;
    }).sort((a, b) => (parseInt(b.quality, 10) || 0) - (parseInt(a.quality, 10) || 0));
  }

  function parseSubtitles(value) {
    if (!value || typeof value !== "string") return [];
    return value.split(/,(?=\[)/).map(part => {
      const m = part.match(/^\[([^\]]+)\](.+)$/);
      if (!m) return null;
      const url = cleanUrl(m[2]);
      return url ? {lang: m[1].trim(), url} : null;
    }).filter(Boolean).slice(0, 12);
  }

  function metadataFromPage() {
    const scripts = [...document.scripts].map(x => x.textContent || "").join("\n");
    const initial = /initCDN(Series|Movies)Events\(\s*(\d+)\s*,\s*(\d+)/.exec(scripts);
    const isSeries = initial ? initial[1] === "Series" : !!document.querySelector(".b-simple_episode__item");
    const filmId = initial?.[2] || document.querySelector("[data-post_id]")?.getAttribute("data-post_id");
    const hash = location.hash || "";
    const part = key => (new RegExp("(?:^|[-#])" + key + ":(\\d+)").exec(hash) || [])[1];
    const activeTranslator = document.querySelector(".b-translator__item.active, .b-translator__item.selected, .b-translator__item.current");
    const translatorId = part("t") || activeTranslator?.getAttribute("data-translator_id") || activeTranslator?.getAttribute("data-id") || initial?.[3];
    const activeEpisode = document.querySelector(".b-simple_episode__item.active, .b-simple_episode__item.current");
    const season = part("s") || activeEpisode?.getAttribute("data-season_id");
    const episode = part("e") || activeEpisode?.getAttribute("data-episode_id");
    const heading = document.querySelector("h1")?.textContent?.trim() || document.title.replace(/\s*[|–-]\s*.*$/, "");
    const epLabel = isSeries && season && episode ? ` · S${season}E${episode}` : "";
    return {isSeries, filmId, translatorId, season, episode,
      title: (heading + epLabel).trim(), sourcePage: location.href,
      is_camrip: activeTranslator?.getAttribute("data-camrip") || "0",
      is_ads: activeTranslator?.getAttribute("data-ads") || "0",
      is_director: activeTranslator?.getAttribute("data-director") || "0"};
  }

  async function getSources() {
    const info = metadataFromPage();
    if (!info.filmId || !info.translatorId) {
      throw new Error("Не нашёл ID фильма или перевода. Выбери перевод и эпизод на сайте, затем обнови страницу.");
    }
    if (info.isSeries && (!info.season || !info.episode)) {
      throw new Error("Выбери конкретную серию на сайте, чтобы появились сезон и эпизод в URL.");
    }
    const fields = new URLSearchParams({
      id: info.filmId,
      translator_id: info.translatorId,
      favs: "",
      action: info.isSeries ? "get_stream" : "get_movie"
    });
    if (info.isSeries) {
      fields.set("season", info.season);
      fields.set("episode", info.episode);
    } else {
      fields.set("is_camrip", info.is_camrip);
      fields.set("is_ads", info.is_ads);
      fields.set("is_director", info.is_director);
    }
    const response = await fetch("/ajax/get_cdn_series/?t=" + Date.now(), {
      method: "POST", body: fields.toString(), credentials: "include",
      headers: {"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8", "X-Requested-With": "XMLHttpRequest"}
    });
    if (!response.ok) throw new Error("HDrezka вернула HTTP " + response.status);
    let payload;
    try { payload = await response.json(); }
    catch (_) { throw new Error("Сайт вернул не JSON; возможно, нужна авторизация или капча."); }
    if (!payload.success) throw new Error(payload.message || "Не удалось получить поток.");
    const videos = parseQualities(payload.url);
    if (!videos.length) throw new Error("Не нашёл прямые MP4-ссылки. HLS, DASH и защищённые потоки в MVP не поддерживаются.");
    return { ...info, videos, subtitles: parseSubtitles(payload.subtitle) };
  }
  window.PS4RezkaAdapter = Object.freeze({getSources, parseQualities, parseSubtitles, metadataFromPage});
})();
