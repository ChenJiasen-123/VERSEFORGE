import http.client
import json
import tempfile
import threading
import time
from pathlib import Path
import unittest
from web_server import make_server


class WebTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        def runner(prompt, genre, preference, previous, progress):
            progress('writing')
            return {'status': 'completed', 'poem': {'title': '测试诗', 'lines': ['题目：' + prompt]}}
        self.server = make_server(0, Path(self.folder.name) / 'jobs.sqlite', runner)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_port
        self.cookie = None
        self.csrf = None

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.server.studio.pool.shutdown(wait=True)
        self.thread.join()
        self.folder.cleanup()

    def request(self, method, path, data=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        supplied = {'Content-Type': 'application/json'}
        if self.cookie: supplied['Cookie'] = self.cookie
        if self.csrf: supplied['X-CSRF-Token'] = self.csrf
        supplied.update(headers or {})
        connection.request(method, path, json.dumps(data).encode('utf-8') if data is not None else None, supplied)
        response = connection.getresponse()
        body, status, cookie = response.read(), response.status, response.getheader('Set-Cookie')
        connection.close()
        return status, body, cookie

    def session(self):
        status, body, cookie = self.request('GET', '/api/session')
        self.assertEqual(status, 200)
        self.cookie, self.csrf = cookie.split(';')[0], json.loads(body)['csrf']

    def test_page_is_served_but_source_and_secrets_are_not(self):
        self.assertEqual(self.request('GET', '/')[0], 200)
        for path in ('/.env', '/web_server.py', '/../.env', '/api/jobs'):
            self.assertIn(self.request('GET', path)[0], (401, 404))

    def test_paid_generation_requires_session_csrf_and_same_origin(self):
        self.assertEqual(self.request('POST', '/api/jobs', {'prompt': '雨后'})[0], 403)
        self.session()
        self.assertEqual(self.request('POST', '/api/jobs', {'prompt': '雨后'}, {'Origin': 'https://foreign.example'})[0], 403)
        self.assertEqual(self.request('POST', '/api/jobs', {'prompt': '雨后'}, {'X-CSRF-Token': 'invalid'})[0], 403)

    def test_host_rebinding_is_rejected(self):
        self.assertEqual(self.request('GET', '/api/session', headers={'Host': 'foreign.example'})[0], 403)

    def test_create_poll_and_history_retain_the_actual_result(self):
        self.session()
        status, body, _ = self.request('POST', '/api/jobs', {'prompt': '一场雨之后', 'genre': 'auto'})
        self.assertEqual(status, 202)
        identity = json.loads(body)['id']
        for _ in range(30):
            status, body, _ = self.request('GET', '/api/jobs/' + identity)
            job = json.loads(body)
            if job['status'] == 'completed': break
            time.sleep(.02)
        self.assertEqual(job['result']['poem']['lines'], ['题目：一场雨之后'])
        self.assertEqual(job['request']['prompt'], '一场雨之后')
        self.assertEqual(len(json.loads(self.request('GET', '/api/jobs')[1])), 1)

    def test_bad_input_is_rejected_before_worker_submission(self):
        self.session()
        for data in (
            {'prompt': ''}, {'prompt': '诗', 'genre': 'invalid'},
            {'prompt': '夜雨', 'style_mode': 'invalid'},
            {'prompt': '夜雨', 'expansion_mode': 'invalid'},
            {'prompt': '夜雨', 'expansion_model': 'gpt-4'},
            {'prompt': '夜雨', 'auto_polish': 'invalid'},
            {'prompt': ['not text']},
        ):
            self.assertEqual(self.request('POST', '/api/jobs', data)[0], 400)

    def test_auto_polish_toggle_controls_independent_editor_option(self):
        captured = []
        def fake_studio(prompt, genre, preference, previous, progress, **kwargs):
            captured.append((genre, kwargs))
            return {'status': 'completed', 'poem': {'title': '测试诗', 'lines': ['一行']}}
        import web_server
        orig_ref = web_server.run_studio
        web_server.run_studio = fake_studio
        self.server.studio.runner = fake_studio
        try:
            self.session()
            id_default = json.loads(self.request('POST', '/api/jobs', {'prompt': '一场雨之后'})[1])['id']
            id_on = json.loads(self.request('POST', '/api/jobs', {'prompt': '一场雨之后', 'auto_polish': 'on'})[1])['id']
            for jid in (id_default, id_on):
                for _ in range(30):
                    job = json.loads(self.request('GET', '/api/jobs/' + jid)[1])
                    if job['status'] == 'completed':
                        break
                    time.sleep(.02)
            self.assertEqual(captured[0][0], 'modern')
            self.assertEqual(captured[0][1]['expansion_mode'], 'expand_v1')
            self.assertEqual(captured[0][1]['expansion_model'], 'deepseek-reasoner')
            self.assertEqual(captured[0][1]['style_mode'], 'rpe_v6')
            self.assertFalse(captured[0][1]['independent_editor'])
            self.assertTrue(captured[1][1]['independent_editor'])
        finally:
            web_server.run_studio = orig_ref

    def test_worker_failure_is_bounded_and_keeps_phase_without_raw_exception(self):
        def failing(*args, progress, **kwargs):
            progress('writing')
            raise RuntimeError('private-provider-response')
        self.server.studio.runner = failing
        self.session()
        identity = json.loads(self.request('POST', '/api/jobs', {'prompt': '夜雨'})[1])['id']
        for _ in range(30):
            _, body, _ = self.request('GET', '/api/jobs/' + identity)
            row = json.loads(body)
            if row['status'] == 'failed': break
            time.sleep(.02)
        self.assertEqual(row['result']['phase'], 'writing')
        self.assertNotIn('private-provider-response', body.decode('utf-8'))

    def test_queue_is_bounded_while_a_job_is_running(self):
        release = threading.Event()
        def blocking(*args, progress, **kwargs):
            release.wait(5)
            return {'status': 'completed', 'poem': {'title': '测试', 'lines': ['测试']}}
        self.server.studio.runner = blocking
        self.session()
        try:
            for _ in range(3):
                self.assertEqual(self.request('POST', '/api/jobs', {'prompt': '夜雨'})[0], 202)
            self.assertEqual(self.request('POST', '/api/jobs', {'prompt': '夜雨'})[0], 429)
        finally:
            release.set()
