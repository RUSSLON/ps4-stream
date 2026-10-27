import http.client
import json
import os
import socket
import subprocess
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))
import app


class LocalService(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sock = socket.socket()
        sock.bind(('127.0.0.1', 0))
        cls.port = sock.getsockname()[1]
        sock.close()
        env = {**os.environ, 'PORT': str(cls.port), 'API_KEY': 'test_long_secure_key_for_http', 'PYTHONUNBUFFERED':'1'}
        cls.proc = subprocess.Popen([sys.executable, 'app.py'], cwd=ROOT / 'server', env=env,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        for _ in range(100):
            try:
                if cls.request('GET', '/healthz')[0] == 200:
                    break
            except (OSError, http.client.HTTPException):
                time.sleep(.05)
        else:
            raise RuntimeError('Service failed to start')

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(timeout=5)
        cls.proc.stdout.close()
        cls.proc.stderr.close()

    @classmethod
    def request(cls, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', cls.port, timeout=5)
        conn.request(method, path, body=body, headers=headers or {})
        resp = conn.getresponse()
        data = resp.read()
        result = (resp.status, data, dict(resp.getheaders()))
        conn.close()
        return result

    def upload(self, pin, auth=True):
        payload = json.dumps({'pin':pin,'title':'Серия','url':'https://cdn.example.org/movie.mp4?tok=xyz',
                              'quality':'1080p','subtitles':[]}).encode()
        return self.request('POST','/api/launch',body=payload,headers={
            'Content-Type':'application/json', **({'Authorization':'Bearer test_long_secure_key_for_http'} if auth else {})})

    def test_01_html_and_upload(self):
        r = self.request('GET','/')
        self.assertEqual(r[0],200)
        self.assertIn(b'name="pin"',r[1]);self.assertNotIn(b'/tv/',r[1])
        self.assertIn('no-store',r[2]['Cache-Control'])
        self.assertEqual(self.upload('0123',auth=False)[0],401)
        self.assertEqual(self.upload('aaa1')[0],400)
        self.assertEqual(self.upload(2345)[0],400)
        self.assertEqual(self.upload('0123')[0],200)
        self.assertEqual(self.upload('0123')[0],409)

    def test_02_code_redemption_and_session(self):
        self.assertEqual(self.upload('3812')[0],200)
        form={'Content-Type':'application/x-www-form-urlencoded'}
        wrong=self.request('POST','/',b'pin=3813',form)
        self.assertEqual(wrong[0],400)
        self.assertIn('Неверный'.encode('utf-8'),wrong[1])
        good=self.request('POST','/',b'pin=3812',form)
        self.assertEqual(good[0],200)
        self.assertIn(b'movie.mp4',good[1]);self.assertIn(b'ps4_view=',good[2].get('Set-Cookie','').encode())
        self.assertNotIn(b'3812',good[1]);self.assertNotIn(b'ps4_view=',good[1])
        cookie=good[2]['Set-Cookie'].split(';',1)[0]
        self.assertIn('HttpOnly',good[2]['Set-Cookie'])
        self.assertIn('Secure',good[2]['Set-Cookie'])
        follow=self.request('GET','/',headers={'Cookie':cookie})
        self.assertEqual(follow[0],200);self.assertIn(b'movie.mp4',follow[1])
        self.assertEqual(self.request('GET','/')[0],200)
        self.assertIn(b'name="pin"',self.request('GET','/')[1])
        self.assertIn(b'name="pin"',self.request('GET','/?new=1',headers={'Cookie':cookie})[1])
        self.assertEqual(self.request('POST','/',b'pin=3812',form)[0],400)

    def test_03_one_pending_pin_only(self):
        self.assertEqual(self.upload('1111')[0],200)
        self.assertEqual(self.upload('2222')[0],200)
        form={'Content-Type':'application/x-www-form-urlencoded'}
        self.assertEqual(self.request('POST','/',b'pin=1111',form)[0],400)
        self.assertEqual(self.request('POST','/',b'pin=2222',form)[0],200)
        self.assertEqual(self.request('GET','/tv/unpredictable')[0],404)
        self.assertEqual(self.request('GET','/healthz')[0],200)

    def test_04_html_escaping(self):
        html = app.render_player({'url':'https://x.test/a.mp4', 'title':'</script><script>alert(1)</script>', 'subtitles':[]})
        self.assertNotIn(b'</script><script>alert(1)',html)
        self.assertIn(b'\\u003c/script\\u003e',html)
        self.assertNotIn(b'name="pin"',html)


class Validations(unittest.TestCase):
    def test_sanitization(self):
        good = app.sanitize({'title':'Серия', 'url':'https://x.example/a.mp4',
                             'subtitles':[{'lang':'Русский','text':'00:00:01.000 --> 00:00:04.000\nПривет'}]})
        self.assertEqual(good['subtitles'][0]['lang'],'Русский')
        for bad in ['javascript:alert(1)', 'file:///etc/passwd', 'https://user:pwd@example.com/', '']:
            with self.assertRaises(ValueError):app.sanitize({'url':bad})
        with self.assertRaises(ValueError):app.sanitize({'url':'https://x.example/a.mp4','subtitles':'bad'})


if __name__ == '__main__': unittest.main()
