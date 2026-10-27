import http.client
import hashlib
import json
import os
import subprocess
import sys
import time
import unittest
import socket
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'server'))
import app

class RenderTests(unittest.TestCase):
    def test_sanitization(self):
        good = app.sanitize({'title':'Новая серия', 'quality':'1080p', 'url':'https://cdn.example.org/film.mp4?key=abc', 'subtitles':[{'lang':'Русский', 'text':'1\n00:00:01.000 --> 00:00:04.000\nПривет'}]})
        self.assertEqual(good['subtitles'][0]['lang'], 'Русский')
        for bad in ['javascript:alert(1)', 'file:///etc/passwd', 'https://user:pwd@example.com/', '']:
            with self.assertRaises(ValueError): app.sanitize({'url':bad})

    def test_html_escape(self):
        html = app.render_player({'url':'https://x.test/a.mp4','title':'</script><script>alert(1)</script>', 'subtitles':[]})
        self.assertNotIn(b'</script><script>alert(1)', html)
        self.assertIn(b'\\u003c/script\\u003e', html)

    def test_http(self):
        sock=socket.socket();sock.bind(('127.0.0.1', 0));port=sock.getsockname()[1];sock.close()
        env={**os.environ, 'PORT':str(port), 'API_KEY':'test_super_secret_long_key', 'TV_KEY':'tv-secret-long-and-random', 'RENDER_EXTERNAL_URL':'https://sample.onrender.com'}
        p = subprocess.Popen([sys.executable, 'app.py'],cwd=ROOT/'server',env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        try:
            for _ in range(30):
                try:
                    c=http.client.HTTPConnection('127.0.0.1', port, timeout=1); c.request('GET','/healthz'); r=c.getresponse();data=r.read();c.close()
                    if r.status==200:break
                except OSError: time.sleep(.1)
            else:self.fail('server did not start')
            def request(method, path, body=None, headers=None):
                c=http.client.HTTPConnection('127.0.0.1', port, timeout=3)
                c.request(method,path,body=body,headers=headers or {})
                r=c.getresponse();val=(r.status,r.read(),dict(r.getheaders()));c.close();return val
            body=json.dumps({'title':'Серия', 'url':'https://cdn.example.org/film.mp4?key=abc','quality':'720p', 'subtitles':[]}).encode()
            a=request('POST','/api/launch',body,{'Content-Type':'application/json'})
            self.assertEqual(a[0],401)
            a=request('POST','/api/launch',body,{'Content-Type':'application/json', 'Authorization':'Bearer test_super_secret_long_key'})
            self.assertEqual(a[0],200)
            res=json.loads(a[1])
            self.assertEqual(res['url'],'https://sample.onrender.com/tv/' + hashlib.sha256(b'ps4-stream-tv-v1:tv-secret-long-and-random').hexdigest()[:24])
            b=request('GET','/tv/' + hashlib.sha256(b'ps4-stream-tv-v1:tv-secret-long-and-random').hexdigest()[:24])
            self.assertEqual(b[0],200)
            self.assertIn(b'film.mp4',b[1])
            self.assertEqual(request('GET','/tv/wrong')[0],404)
            self.assertEqual(request('GET','/healthz')[0],200)
        finally:
            p.terminate();p.wait(timeout=3)

if __name__=='__main__':unittest.main()
