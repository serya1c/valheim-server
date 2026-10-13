"""Landing audio through the real HTTP handler, without starting Steam or a game."""
import collections
import hashlib
from html.parser import HTMLParser
import http.client
from pathlib import Path
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
import server


class Tags(HTMLParser):
    def __init__(self, document):
        super().__init__()
        self.tags = []
        self.header_tags = []
        self.in_header = False
        self.feed(document)

    def handle_starttag(self, tag, attrs):
        if tag == 'header':
            self.in_header = True
        entry = (tag, dict(attrs))
        self.tags.append(entry)
        if self.in_header:
            self.header_tags.append(entry)

    def handle_endtag(self, tag):
        if tag == 'header':
            self.in_header = False


class LandingMusicHttpTests(unittest.TestCase):
    audio_url = '/audio/home-a-place-to-enjoy.mp3'
    original_size = 5_517_108
    original_sha256 = '776bb6de106d93beaa1881847c63cde8f9554166b4e40acb4c3e7fe0efffc65b'

    @classmethod
    def setUpClass(cls):
        cls.audio = (Path(server.__file__).parent / 'static/audio/home-a-place-to-enjoy.mp3').read_bytes()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.manager = server.Manager(Path(self.temp.name))
        self.manager.panel.save({**self.manager.panel.load(), 'auth': server.password_hash('fixture-only-password')})

        class Handler(server.Handler):
            sessions = {}
            attempts = collections.deque(maxlen=100)

        Handler.manager = self.manager
        self.http = server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join()
        for handler in self.manager.log.handlers[:]:
            handler.close()
            self.manager.log.removeHandler(handler)
        self.temp.cleanup()

    def request(self, method='GET', path=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.http.server_port, timeout=5)
        try:
            connection.request(method, path or self.audio_url, headers=headers or {})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def test_full_track_retains_original_bytes_and_is_playable_inline(self):
        status, headers, body = self.request()
        self.assertEqual(status, 200)
        self.assertEqual(body, self.audio)
        self.assertEqual(len(body), self.original_size)
        self.assertEqual(hashlib.sha256(body).hexdigest(), self.original_sha256)
        self.assertEqual(headers['Content-Type'], 'audio/mpeg')
        self.assertEqual(headers['Accept-Ranges'], 'bytes')
        self.assertEqual(headers['Content-Length'], str(self.original_size))
        self.assertNotIn('attachment', headers.get('Content-Disposition', '').lower())

    def test_browser_can_request_bounded_open_ended_and_suffix_ranges(self):
        total = len(self.audio)
        cases = (
            ('bytes=0-127', 0, 127),
            (f'bytes={total - 128}-', total - 128, total - 1),
            ('bytes=-128', total - 128, total - 1),
            (f'bytes={total - 64}-{total + 100}', total - 64, total - 1),
        )
        for value, start, end in cases:
            with self.subTest(range=value):
                status, headers, body = self.request(headers={'Range': value})
                self.assertEqual(status, 206)
                self.assertEqual(body, self.audio[start:end + 1])
                self.assertEqual(headers['Content-Type'], 'audio/mpeg')
                self.assertEqual(headers['Accept-Ranges'], 'bytes')
                self.assertEqual(headers['Content-Range'], f'bytes {start}-{end}/{total}')
                self.assertEqual(headers['Content-Length'], str(end - start + 1))

    def test_unsatisfiable_range_returns_empty_416_with_track_length(self):
        total = len(self.audio)
        status, headers, body = self.request(headers={'Range': f'bytes={total}-'})
        self.assertEqual(status, 416)
        self.assertEqual(headers['Content-Range'], f'bytes */{total}')
        self.assertEqual(headers['Content-Length'], '0')
        self.assertEqual(headers['Accept-Ranges'], 'bytes')
        self.assertEqual(body, b'')

    def test_malformed_or_multiple_ranges_fall_back_to_full_response(self):
        for value in ('bytes=hello', 'bytes=0-127,256-383', 'items=0-127'):
            with self.subTest(range=value):
                status, headers, body = self.request(headers={'Range': value})
                self.assertEqual(status, 200)
                self.assertEqual(body, self.audio)
                self.assertEqual(headers['Content-Length'], str(len(self.audio)))
                self.assertNotIn('Content-Range', headers)
        status, headers, body = self.request(headers={'Range': 'bytes=0-127', 'If-Range': '"old-track"'})
        self.assertEqual(status, 200)
        self.assertEqual(body, self.audio)
        self.assertEqual(headers['Content-Length'], str(len(self.audio)))
        self.assertNotIn('Content-Range', headers)

    def test_head_reports_full_headers_without_body_and_ignores_range(self):
        status, headers, body = self.request('HEAD')
        self.assertEqual(status, 200)
        self.assertEqual(headers['Content-Length'], str(len(self.audio)))
        self.assertEqual(headers['Content-Type'], 'audio/mpeg')
        self.assertEqual(headers['Accept-Ranges'], 'bytes')
        self.assertEqual(body, b'')
        status, headers, body = self.request('HEAD', headers={'Range': 'bytes=0-127'})
        self.assertEqual(status, 200)
        self.assertEqual(headers['Content-Length'], str(len(self.audio)))
        self.assertNotIn('Content-Range', headers)
        self.assertEqual(body, b'')

    def test_background_music_has_only_header_mute_control_and_absent_from_admin(self):
        status, _, body = self.request(path='/')
        self.assertEqual(status, 200)
        document = Tags(body.decode('utf-8'))
        tags = document.tags
        audio = [attrs for tag, attrs in tags if tag == 'audio']
        self.assertEqual(len(audio), 1)
        self.assertEqual(audio[0]['src'], self.audio_url)
        self.assertEqual(audio[0]['preload'], 'none')
        self.assertIn('loop', audio[0])
        self.assertNotIn('autoplay', audio[0])
        self.assertNotIn('controls', audio[0])
        toggles = [attrs for tag, attrs in tags if tag == 'button' and attrs.get('id') == 'ambient-music-toggle']
        self.assertEqual(len(toggles), 1)
        self.assertTrue(toggles[0].get('aria-label'))
        self.assertTrue(toggles[0].get('title'))
        self.assertEqual(toggles[0]['type'], 'button')
        self.assertTrue(any(tag == 'button' and attrs.get('id') == 'ambient-music-toggle'
                            for tag, attrs in document.header_tags))
        for removed_id in ('ambient-music-player', 'ambient-music-volume', 'ambient-music-status', 'ambient-music-label'):
            self.assertFalse(any(attrs.get('id') == removed_id for _, attrs in tags))
        self.assertFalse(any(tag == 'input' and attrs.get('type') == 'range' for tag, attrs in tags))
        self.assertTrue(any(tag == 'script' and attrs.get('src') == '/music.js' for tag, attrs in tags))
        status, headers, script = self.request(path='/music.js')
        self.assertEqual(status, 200)
        self.assertIn('javascript', headers['Content-Type'])
        self.assertGreater(len(script), 0)
        status, _, body = self.request(path='/admin')
        self.assertEqual(status, 200)
        self.assertFalse(any(tag == 'audio' for tag, _ in Tags(body.decode('utf-8')).tags))
        self.assertNotIn(b'/music.js', body)

    def test_first_run_stays_a_wizard_and_does_not_serve_audio(self):
        self.manager.panel.path.unlink()
        self.assertFalse(self.manager.panel.configured)
        status, _, body = self.request(path='/')
        self.assertEqual(status, 200)
        self.assertIn(b'/setup.js', body)
        self.assertNotIn(b'<audio', body)
        self.assertEqual(self.request()[0], 409)
        self.assertEqual(self.request('HEAD')[0], 409)


if __name__ == '__main__':
    unittest.main()
