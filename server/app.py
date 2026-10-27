#!/usr/bin/env python3
"""PS4 Stream v0.4: one-time PIN and opt-in secure HTTP Range relay."""
import hmac
import ipaddress
import socket
import urllib.error
import urllib.request
from html import escape
import json
import os
import secrets
import re
import threading
import time
from collections import defaultdict, deque
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

TTL = 600                      # PIN and rate-limit window
SESSION_TTL = 4 * 3600        # Needed for seeking during long films
STREAM_CHUNK = 64 * 1024
STREAM_SEMAPHORE = threading.BoundedSemaphore(2)
# Deliberately narrow to avoid operating an open proxy to arbitrary URLs.
ALLOWED_VIDEO_HOSTS = frozenset(x.strip().lower() for x in os.environ.get(
    "VIDEO_ALLOWED_HOSTS", "stream.voidboost.one,interactive-examples.mdn.mozilla.net"
).split(",") if x.strip())
RANGE_PATTERN = re.compile(r"^bytes=(?:[0-9]+-[0-9]*|-[1-9][0-9]*)$")
LIMIT = 3 * 1024 * 1024
PIN_PATTERN = re.compile(r'^[0-9]{4}$')
TEMPLATE = Path(__file__).with_name('player.html').read_text(encoding='utf-8')
API_KEY = os.environ.get('API_KEY', '').strip()
LOCK = threading.Lock()
_pending = None    # One PIN waiting to be redeemed, newest upload wins.
_sessions = {}    # Session-cookie hashes -> media, expires after 4 hours.
_failures = defaultdict(deque)
_global_failures = deque()


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
    subtitles = media.get('subtitles') or []
    if not isinstance(subtitles, list):
        raise ValueError('Некорректный формат субтитров')
    result = {
        'title': str(media.get('title') or 'Видео')[:180],
        'quality': str(media.get('quality') or '')[:40],
        'url': validate_url(media.get('url')),
        'subtitles': []
    }
    total = 0
    for sub in subtitles[:8]:
        if not isinstance(sub, dict):
            continue
        lang = str(sub.get('lang') or 'Субтитры')[:80]
        content = sub.get('text')
        if not isinstance(content, str) or '-->' not in content or len(content) > 750000:
            continue
        total += len(content)
        if total > 1500000:
            break
        result['subtitles'].append({'lang': lang, 'text': content})
    return result


def render_player(media):
    # Use the same-origin proxy by default; retain direct URL only for manual fallback.
    media = {**media, 'url': '/api/stream', 'direct_url': media['url']}
    payload = json.dumps(media, ensure_ascii=False, separators=(',', ':'))
    # Escaping is mandatory, including when this JSON is in a non-executable script.
    for original, replacement in [('&', '\\u0026'), ('<', '\\u003c'), ('>', '\\u003e'), ('\u2028', '\\u2028'), ('\u2029', '\\u2029')]:
        payload = payload.replace(original, replacement)
    return TEMPLATE.replace('<!--PS4_DATA-->', '<script id="ps4-payload" type="application/json">' + payload + '</script>').encode('utf-8')


def pin_page(error=''):
    from html import escape
    alert = ('<div class="alert" role="alert">' + escape(error) + '</div>') if error else ''
    html = '''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PS4 Stream · Вход</title>
<style>*{box-sizing:border-box}html,body{margin:0;min-height:100%;background:#090e1c;color:#f6f7ff;font-family:Arial,Helvetica,sans-serif}body{min-height:100vh;display:flex;align-items:center;justify-content:center;background:radial-gradient(ellipse at 50% 5%,#283155 0%,#090e1c 65%)}main{width:440px;max-width:calc(100% - 28px);padding:35px 32px;background:#141a2d;border:1px solid #434b70;border-radius:20px;box-shadow:0 30px 90px #0009}.logo{color:#af9aff;letter-spacing:3px;font:bold 14px Arial,sans-serif}.pill{display:inline-block;margin-top:20px;color:#9cdeb7;border:1px solid #316a53;border-radius:30px;padding:7px 11px;font-size:12px}h1{font-size:30px;line-height:1.15;margin:16px 0 9px}.sub{color:#aebbd3;line-height:1.5;margin-bottom:25px}label{display:block;font-size:13px;font-weight:bold;margin:0 0 9px}input{display:block;width:100%;font:bold 42px/1 Arial,sans-serif;text-align:center;letter-spacing:15px;color:white;background:#0b1122;border:2px solid #505d8d;border-radius:13px;padding:15px 12px;outline:none}input:focus{border-color:#ad98ff}button{width:100%;padding:17px;border:0;border-radius:12px;background:linear-gradient(110deg,#7558fa,#3c88fd);font:bold 17px Arial,sans-serif;color:#fff;cursor:pointer;margin-top:16px}button:focus{outline:3px solid #fff}.alert{color:#ffd5d7;background:#502b36;padding:12px;border-radius:9px;margin-bottom:16px;line-height:1.4}.foot{font-size:12px;color:#8d9ab5;margin-top:23px;line-height:1.5}small{display:block;color:#91a2c5;font-size:13px;margin-top:10px}</style></head><body><main><div class="logo">◈ PS4 STREAM</div><span class="pill">PLAYSTATION PLAYER</span><h1>Ввод кода</h1><p class="sub">Отправь фильм из расширения Chrome, затем введи четырёхзначный код с экрана ноутбука.</p>'''+ alert +'''<form method="post" action="/"><label for="pin">КОД ПОДКЛЮЧЕНИЯ</label><input id="pin" name="pin" type="text" inputmode="numeric" pattern="[0-9]{4}" maxlength="4" minlength="4" placeholder="0000" autocomplete="off" required autofocus><button type="submit">Начать просмотр →</button></form><small>Код действует 10 минут и только один раз.</small><div class="foot">Если код истёк, повтори отправку из Chrome. По умолчанию видео идёт через Render. Это экспериментальный режим: видеосервер может отказать Render в доступе.</div></main></body></html>'''
    return html.encode('utf-8')


def cookie_hash(raw):
    import hashlib
    return hashlib.sha256(raw.encode('ascii')).hexdigest()


def cleanup(now):
    global _pending
    if _pending and now - _pending['when'] >= TTL:
        _pending = None
    for sid, s in list(_sessions.items()):
        if now - s['when'] >= SESSION_TTL:
            del _sessions[sid]
    for key in list(_failures):
        q = _failures[key]
        while q and now - q[0] >= TTL:
            q.popleft()
        if not q:
            del _failures[key]
    while _global_failures and now - _global_failures[0] >= TTL:
        _global_failures.popleft()


class App(BaseHTTPRequestHandler):
    server_version = 'PS4Stream/0.4'

    def log_message(self, fmt, *args):
        # Do not log signed CDN links, cookies, API key, PINs.
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
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def cors(self):
        return {'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Methods': 'POST, OPTIONS',
                'Access-Control-Allow-Headers': 'Authorization, Content-Type', 'Access-Control-Max-Age': '600'}

    def do_OPTIONS(self):
        if urlsplit(self.path).path == '/api/launch':
            self.reply(204, '', 'text/plain', self.cors())
        else:
            self.reply(404, '')

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == '/healthz':
            self.reply(200, '{"ok":true}', 'application/json')
            return
        if path == '/api/stream':
            self.stream_video()
            return
        if path == '/api/check':
            self.check_video()
            return
        if path != '/':
            self.reply(404, '<h2>Страница не найдена</h2>')
            return
        new = 'new=1' in urlsplit(self.path).query.split('&')
        session = None if new else self.get_session()
        headers = {'Set-Cookie': 'ps4_view=; HttpOnly; SameSite=Lax; Secure; Path=/; Max-Age=0'} if new else None
        if session:
            self.reply(200, render_player(session['media']))
        else:
            self.reply(200, pin_page(), extras=headers)

    def get_session(self):
        try:
            jar = cookies.SimpleCookie()
            jar.load(self.headers.get('Cookie', ''))
            raw = jar['ps4_view'].value if 'ps4_view' in jar else None
        except cookies.CookieError:
            return None
        if not raw or len(raw) >= 300:
            return None
        with LOCK:
            cleanup(time.time())
            return _sessions.get(cookie_hash(raw))

    @staticmethod
    def verify_upstream(raw_url):
        """Allow only explicitly configured public HTTPS hosts and port 443.

        Do not auto-follow redirects (they can target the metadata service).
        This deliberately does not forward browser cookies or spoof Referer.
        """
        parts = urlsplit(raw_url)
        if (parts.scheme != 'https' or parts.hostname not in ALLOWED_VIDEO_HOSTS or
                parts.username or parts.password or parts.port not in (None, 443)):
            raise ValueError('Домен видеосервера не разрешён. Укажи его в VIDEO_ALLOWED_HOSTS на Render.')
        addresses = socket.getaddrinfo(parts.hostname, 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(info[4][0]).is_global for info in addresses):
            raise ValueError('Заблокирован внутренний или недоступный IP-адрес видеосервера.')
        return raw_url

    @staticmethod
    def open_upstream(url, range_header):
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, request, fp, code, msg, headers, newurl):
                return None
        req = urllib.request.Request(url, headers={
            'Accept-Encoding': 'identity',
            'User-Agent': 'PS4Stream/0.4',
            **({'Range': range_header} if range_header else {})
        })
        return urllib.request.build_opener(NoRedirect).open(req, timeout=12)

    def check_video(self):
        session = self.get_session()
        if not session:
            self.reply(401, '<h2>Сначала введи PIN на главной странице.</h2>')
            return
        status, detail = 502, 'Нет ответа'
        try:
            url = self.verify_upstream(session['media']['url'])
            with self.open_upstream(url, 'bytes=0-1023') as upstream:
                code = upstream.status
                content_type = upstream.headers.get('Content-Type', '')
                chunk = upstream.read(1024)
                if code in (200, 206) and not content_type.lower().startswith(('text/html', 'application/json')):
                    status = 200
                    detail = 'Render получает видео. HTTP %d, тип %s, получено %d байт. Можно попробовать режим RENDER.' % (code, content_type or 'не указан', len(chunk))
                else:
                    detail = 'Видеосервер ответил HTTP %d, тип %s. Возможно, вместо MP4 приходит ошибка или HTML.' % (code, content_type or 'не указан')
        except urllib.error.HTTPError as exc:
            detail = 'Видеосервер отказал Render: HTTP %d. Вероятна привязка ссылки к IP, сроку или ограничениям доступа.' % exc.code
        except (ValueError, OSError, urllib.error.URLError) as exc:
            detail = str(exc)
        markup = ('<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
                  '<style>body{font:18px/1.6 Arial;background:#101626;color:white;max-width:680px;margin:10vh auto;padding:25px}'
                  'a{color:#b7a8ff}</style><h2>Проверка доступа с Render</h2><p>' + escape(detail) + '</p>'
                  '<p>Это проверка первых 1024 байт, не гарантия воспроизведения всего фильма.</p><a href="/">Вернуться к плееру</a></html>')
        self.reply(status, markup)

    def stream_video(self):
        session = self.get_session()
        if not session:
            self.reply(401, 'Сессия истекла. Отправь видео заново.', 'text/plain; charset=utf-8')
            return
        request_range = self.headers.get('Range')
        if request_range and not RANGE_PATTERN.fullmatch(request_range):
            self.reply(416, 'Поддерживается только один диапазон bytes.', 'text/plain; charset=utf-8')
            return
        if not STREAM_SEMAPHORE.acquire(blocking=False):
            self.reply(429, 'Слишком много одновременных подключений', 'text/plain; charset=utf-8')
            return
        try:
            try:
                url = self.verify_upstream(session['media']['url'])
                upstream = self.open_upstream(url, request_range)
            except urllib.error.HTTPError as exc:
                self.reply(502, 'Видеосервер отказал Render: HTTP %d. Открой /api/check.' % exc.code, 'text/plain; charset=utf-8')
                return
            except (ValueError, OSError, urllib.error.URLError) as exc:
                self.reply(502, 'Render не может получить видеопоток. Открой /api/check.', 'text/plain; charset=utf-8')
                return
            with upstream:
                status = upstream.status
                content_type = upstream.headers.get('Content-Type', 'video/mp4')
                content_range = upstream.headers.get('Content-Range')
                length = upstream.headers.get('Content-Length')
                # Do not stream a redirected login page or an error response as video.
                if (status not in (200, 206) or
                    content_type.lower().startswith(('text/', 'application/json')) or
                    (status == 206 and not content_range)):
                    self.reply(502, 'CDN не вернул корректный поток MP4. Проверь /api/check.', 'text/plain; charset=utf-8')
                    return
                # If upstream ignores a nonzero seek, sending the full video
                # would wrongly make the playback jump to the beginning.
                if request_range and status == 200 and not request_range.startswith('bytes=0-'):
                    self.reply(502, 'CDN не поддерживает перемотку Range.', 'text/plain; charset=utf-8')
                    return
                self.send_response(status)
                self.send_header('Content-Type', content_type)
                self.send_header('Accept-Ranges', upstream.headers.get('Accept-Ranges', 'bytes' if status == 206 else 'none'))
                if content_range:
                    self.send_header('Content-Range', content_range)
                if length and length.isdecimal():
                    self.send_header('Content-Length', length)
                self.send_header('Cache-Control', 'private, no-store')
                self.send_header('Referrer-Policy', 'no-referrer')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.send_header('Connection', 'close')
                self.end_headers()
                self.close_connection = True
                try:
                    while True:
                        chunk = upstream.read(STREAM_CHUNK)
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError, TimeoutError, OSError):
                    pass
        finally:
            STREAM_SEMAPHORE.release()

    def do_POST(self):
        if urlsplit(self.path).path == '/api/launch':
            self.launch()
        elif urlsplit(self.path).path == '/':
            self.redeem()
        else:
            self.reply(404, '')

    def launch(self):
        global _pending
        if not API_KEY:
            self.reply(503, '{"ok":false,"error":"На Render нужно настроить API_KEY"}', 'application/json', self.cors())
            return
        if not hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + API_KEY):
            self.reply(401, '{"ok":false,"error":"Неверный API_KEY"}', 'application/json', self.cors())
            return
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= LIMIT:
                raise ValueError('Слишком большой запрос')
            data = json.loads(self.rfile.read(size))
            if not isinstance(data, dict) or not isinstance(data.get('pin'), str) or not PIN_PATTERN.fullmatch(data['pin']):
                raise ValueError('Нужен четырёхзначный PIN')
            media = sanitize(data)
            now = time.time()
            with LOCK:
                cleanup(now)
                if _pending and hmac.compare_digest(_pending['pin'], data['pin']):
                    self.reply(409, '{"ok":false,"error":"PIN уже занят, повтори отправку"}', 'application/json', self.cors())
                    return
                _pending = {'pin': data['pin'], 'when': now, 'media': media}
            self.reply(200, json.dumps({'ok': True, 'expires_in_seconds': TTL}, ensure_ascii=False), 'application/json', self.cors())
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self.reply(400, json.dumps({'ok': False, 'error': str(exc)}, ensure_ascii=False), 'application/json', self.cors())

    def redeem(self):
        global _pending
        if self.headers.get('Content-Type', '').split(';')[0].strip() != 'application/x-www-form-urlencoded':
            self.reply(415, pin_page('Неподдерживаемый формат запроса'))
            return
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size < 256:
                raise ValueError('Неверный размер запроса')
            form = parse_qs(self.rfile.read(size).decode('utf-8'), keep_blank_values=True)
            pin = form.get('pin', [''])[0]
        except (ValueError, UnicodeError):
            self.reply(400, pin_page('Некорректный код'))
            return
        # Pairing is one-shot. A short-lived HttpOnly cookie permits refresh on the same console.
        client = self.client_address[0]  # Never trust user-controlled forwarded headers for rate limiting.
        now = time.time()
        with LOCK:
            cleanup(now)
            if len(_failures[client]) >= 7 or len(_global_failures) >= 100:
                self.reply(429, pin_page('Слишком много попыток. Повтори позже.'), extras={'Retry-After': '600'})
                return
            if not PIN_PATTERN.fullmatch(pin or '') or not _pending or not hmac.compare_digest(pin, _pending['pin']):
                _failures[client].append(now)
                _global_failures.append(now)
                self.reply(400, pin_page('Неверный или истёкший код.'))
                return
            media = _pending['media']
            _pending = None
            session_token = secrets.token_urlsafe(32)
            _sessions[cookie_hash(session_token)] = {'media': media, 'when': now}
        self.reply(200, render_player(media), extras={
            'Set-Cookie': 'ps4_view=' + session_token + '; HttpOnly; SameSite=Lax; Secure; Path=/; Max-Age=14400'
        })


def main():
    port = int(os.environ.get('PORT', '10000'))
    if not API_KEY:
        print('WARNING: API_KEY required before uploads work.', flush=True)
    httpd = ThreadingHTTPServer(('0.0.0.0', port), App)
    httpd.daemon_threads = True
    print('PS4 Stream v0.4 listening on port', port, flush=True)
    httpd.serve_forever()


if __name__ == '__main__':
    main()
