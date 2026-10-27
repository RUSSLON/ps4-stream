#!/usr/bin/env python3
"""Minimal Render web app for PS4 Stream. No CDN video proxy, no third-party deps."""
import hmac
import hashlib
import json
import os
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

TTL = 600
LIMIT = 3 * 1024 * 1024
TEMPLATE = Path(__file__).with_name('player.html').read_text(encoding='utf-8')
API_KEY = os.environ.get('API_KEY', '').strip()
TV_KEY = os.environ.get('TV_KEY', '').strip()
TV_SLUG = hashlib.sha256(('ps4-stream-tv-v1:' + TV_KEY).encode('utf-8')).hexdigest()[:24] if TV_KEY else ''
_lock = threading.Lock()
_latest = None


def validate_url(value):
    if not isinstance(value, str) or len(value) > 4096:
        raise ValueError('Неверная ссылка на видео')
    obj = urlsplit(value)
    if obj.scheme not in ('https', 'http') or not obj.hostname or obj.username or obj.password:
        raise ValueError('Разрешены только обычные HTTP(S) ссылки')
    return value


def sanitize(media):
    if not isinstance(media, dict):
        raise ValueError('Отсутствуют данные видео')
    result = {
        'title': str(media.get('title') or 'Видео')[:180],
        'quality': str(media.get('quality') or '')[:40],
        'url': validate_url(media.get('url')),
        'subtitles': []
    }
    total_sub_chars = 0
    for item in media.get('subtitles', [])[:8]:
        if not isinstance(item, dict):
            continue
        lang = str(item.get('lang') or 'Субтитры')[:80]
        content = item.get('text')
        if not isinstance(content, str) or '-->' not in content or len(content) > 750_000:
            continue
        total_sub_chars += len(content)
        if total_sub_chars > 1_500_000:
            break
        result['subtitles'].append({'lang': lang, 'text': content})
    return result


def render_player(media):
    payload = json.dumps(media, ensure_ascii=False, separators=(',', ':'))
    # JSON inside <script type=application/json> still needs HTML escaping.
    for old, new in [('&', '\\u0026'), ('<', '\\u003c'), ('>', '\\u003e'), ('\u2028', '\\u2028'), ('\u2029', '\\u2029')]:
        payload = payload.replace(old, new)
    return TEMPLATE.replace('<!--PS4_DATA-->', '<script id="ps4-payload" type="application/json">' + payload + '</script>').encode('utf-8')


HOME = '''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>PS4 Stream</title>
<style>body{background:#0b1020;color:#f2f4ff;font:17px system-ui,sans-serif;margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center}main{max-width:600px;padding:32px;border:1px solid #293554;border-radius:20px;background:#141c31}small{color:#a5b2cf}.logo{color:#a18aff;font-weight:bold;letter-spacing:3px}h1{font-size:35px}</style><main><div class="logo">◆ PS4 STREAM</div><h1>Плеер для PlayStation</h1><p>Выбери видео в Chrome и отправь сюда через расширение PS4 Stream. На консоли открой свою персональную ссылку /tv/…</p><small>Без проксирования видеопотока. Работает только с прямыми ссылками, доступными браузеру PS4.</small></main></html>'''
WAIT = '''<!doctype html><html lang="ru"><meta charset="utf-8"><meta http-equiv="refresh" content="20"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PS4 Stream · ожидание</title>
<style>body{background:#0c1120;color:#f4f5ff;font:22px Arial,sans-serif;text-align:center;padding:15vh 20px}.sub{color:#a9b5d3;font-size:17px}button{border:0;border-radius:12px;background:#806bff;color:white;padding:18px;font-size:20px}</style><h2>◆ PS4 STREAM</h2><p>Ожидаем видео из Chrome…</p><p class="sub">Если фильм уже отправлен, страница обновится автоматически.</p><button onclick="location.reload()">Обновить</button></html>'''


class App(BaseHTTPRequestHandler):
    server_version = 'PS4Stream/0.2'

    def log_message(self, fmt, *args):
        # Do not log URLs containing signed media/CDN tokens or secret TV room key.
        pass

    def reply(self, status, content, mime='text/html; charset=utf-8', extras=None):
        data = content if isinstance(content, bytes) else content.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        if extras:
            for k, v in extras.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def cors(self):
        # Bearer authentication is always required for write operations.
        return {'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Methods': 'POST, OPTIONS',
                'Access-Control-Allow-Headers': 'Authorization, Content-Type', 'Access-Control-Max-Age': '600'}

    def do_OPTIONS(self):
        if self.path == '/api/launch':
            self.reply(204, '', 'text/plain', self.cors())
        else:
            self.reply(404, '')

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == '/healthz':
            self.reply(200, '{"ok":true}', 'application/json')
        elif path == '/':
            self.reply(200, HOME)
        elif TV_KEY and path == '/tv/' + TV_SLUG:
            with _lock:
                snapshot = _latest
            if snapshot and time.time() - snapshot['when'] < TTL:
                self.reply(200, render_player(snapshot['media']))
            else:
                self.reply(200, WAIT)
        else:
            self.reply(404, '<h2>Страница не найдена</h2>')

    def do_POST(self):
        global _latest
        if self.path != '/api/launch':
            self.reply(404, '{}', 'application/json', self.cors())
            return
        if not API_KEY or not TV_KEY:
            self.reply(503, '{"ok":false,"error":"На Render нужно задать API_KEY и TV_KEY"}', 'application/json', self.cors())
            return
        token = self.headers.get('Authorization', '')
        if not hmac.compare_digest(token, 'Bearer ' + API_KEY):
            self.reply(401, '{"ok":false,"error":"Неверный API_KEY"}', 'application/json', self.cors())
            return
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= LIMIT:
                raise ValueError('Слишком большой запрос или не указан Content-Length')
            body = self.rfile.read(size)
            media = sanitize(json.loads(body))
            with _lock:
                _latest = {'when': time.time(), 'media': media}
            # Host is only a hint, never accept arbitrary Host as a redirect target.
            origin = os.environ.get('RENDER_EXTERNAL_URL', '').rstrip('/')
            if not origin:
                origin = 'http://localhost:' + str(self.server.server_port)
            result = json.dumps({'ok': True, 'url': origin + '/tv/' + TV_SLUG, 'expires_in_seconds': TTL}, ensure_ascii=False)
            self.reply(200, result, 'application/json', self.cors())
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self.reply(400, json.dumps({'ok': False, 'error': str(exc)}, ensure_ascii=False), 'application/json', self.cors())


def main():
    port = int(os.environ.get('PORT', '10000'))
    if not (API_KEY and TV_KEY):
        print('WARNING: API_KEY and TV_KEY must be set before accepting uploads', flush=True)
    # Single process/worker required; data is stored in memory for 10 minutes only.
    httpd = ThreadingHTTPServer(('0.0.0.0', port), App)
    httpd.daemon_threads = True
    print('PS4 Stream listening on port', port, flush=True)
    httpd.serve_forever()


if __name__ == '__main__':
    main()
