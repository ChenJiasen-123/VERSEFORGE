"""Loopback-only studio server; no third-party runtime dependencies."""
import argparse
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import secrets
import sqlite3
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4
from poetry_agent.client import load_env, DeepSeekClient
from poetry_agent.aesthetics import failure_code
from poetry_agent.studio import run_studio, STUDIO_PROTOCOL

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / 'web'


class Studio:
    def __init__(self, database, runner=run_studio):
        self.database, self.runner = Path(database), runner
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.tokens = {}
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, created REAL, prompt TEXT, status TEXT, result TEXT, error TEXT, request TEXT)')
            if 'request' not in {row[1] for row in db.execute('PRAGMA table_info(jobs)')}:
                db.execute('ALTER TABLE jobs ADD COLUMN request TEXT')
            db.execute("UPDATE jobs SET status='failed', error='服务曾重启，请重新生成。' WHERE status NOT IN ('completed','failed')")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.database)
        try:
            with db:
                yield db
        finally:
            db.close()

    def update(self, identity, state, result=None, error=None):
        with self.connect() as db:
            db.execute('UPDATE jobs SET status=?, result=COALESCE(?,result), error=? WHERE id=?',
                       (state, json.dumps(result, ensure_ascii=False) if result is not None else None, error, identity))

    def add(self, data):
        with self.lock, self.connect() as db:
            active = db.execute("SELECT count(*) FROM jobs WHERE status NOT IN ('completed','failed')").fetchone()[0]
            if active >= 3:
                raise OverflowError('已有任务正在创作，请稍候。')
            identity = uuid4().hex
            db.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?)', (identity, time.time(), data['prompt'], 'queued', None, None, json.dumps(data, ensure_ascii=False)))
        self.pool.submit(self.work, identity, data)
        return identity

    def work(self, identity, data):
        phase = 'queued'
        def progress(state):
            nonlocal phase
            phase = state
            self.update(identity, state)
        try:
            options = {'independent_editor': True,'candidate_count':2} if self.runner is run_studio else {}
            result = self.runner(data['prompt'], data['genre'], data['preference'], data.get('previous'),
                                 progress=progress, **options)
            self.update(identity, 'completed', result)
        except Exception as error:
            code = failure_code(error)
            messages = {'output_length': '这次创作超出输出上限，请重试或缩短样题。',
                        'workflow_budget_exhausted':'本次创作已达到总预算，未能完成初稿。',
                        'service_error': '创作服务暂时未能完成请求，请稍后再试。'}
            self.update(identity, 'failed', result={'failure_code': code, 'phase': phase},
                        error=messages.get(code, '这次题目理解或生成未完成，请重试。'))

    def jobs(self, identity=None):
        with self.connect() as db:
            db.row_factory = sqlite3.Row
            rows = db.execute('SELECT * FROM jobs WHERE id=?', (identity,)).fetchall() if identity else db.execute('SELECT id,created,prompt,status,error,result FROM jobs ORDER BY created DESC LIMIT 60').fetchall()
        values = [dict(row) for row in rows]
        for row in values:
            if 'result' in row:
                row['result'] = json.loads(row['result']) if row['result'] else None
                if not identity:
                    row['title'] = (row['result'] or {}).get('poem', {}).get('title')
                    del row['result']
            if 'request' in row:
                row['request'] = json.loads(row['request']) if row['request'] else {}
        return values[0] if identity and values else None if identity else values


class Handler(BaseHTTPRequestHandler):
    server_version = 'VERSEFORGE'
    def log_message(self, *_):
        pass

    @property
    def studio(self):
        return self.server.studio

    def send(self, code, payload, content_type='application/json; charset=utf-8', cookie=None):
        body = payload.encode('utf-8') if isinstance(payload, str) else payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'")
        if cookie:
            self.send_header('Set-Cookie', cookie)
        self.end_headers()
        self.wfile.write(body)

    def valid_host(self):
        return self.headers.get('Host') in {f'localhost:{self.server.server_port}', f'127.0.0.1:{self.server.server_port}'}

    def session(self):
        try:
            cookie = SimpleCookie(self.headers.get('Cookie', ''))
            value = cookie.get('verseforge')
            return value.value if value and value.value in self.studio.tokens else None
        except Exception:
            return None

    def do_GET(self):
        if not self.valid_host():
            return self.send(403, {'error': '仅允许本机访问。'})
        path = urlsplit(self.path).path
        if path == '/health':
            return self.send(200, {'application': 'VERSEFORGE', 'pid': os.getpid(), 'workflow_protocol': STUDIO_PROTOCOL})
        if path == '/api/session':
            identity = self.session() or secrets.token_urlsafe(32)
            with self.studio.lock:
                if len(self.studio.tokens) >= 128 and identity not in self.studio.tokens:
                    return self.send(429, {'error': '会话数量已满，请重启本地服务。'})
                self.studio.tokens.setdefault(identity, secrets.token_urlsafe(32))
            try:
                DeepSeekClient()
                configured = True
            except ValueError:
                configured = False
            return self.send(200, {'csrf': self.studio.tokens[identity], 'configured': configured}, cookie=f'verseforge={identity}; HttpOnly; SameSite=Strict; Path=/')
        if path.startswith('/api/'):
            if not self.session():
                return self.send(401, {'error': '请刷新页面后重试。'})
            if path == '/api/jobs':
                return self.send(200, self.studio.jobs())
            identity = path.removeprefix('/api/jobs/')
            if len(identity) == 32 and all(c in '0123456789abcdef' for c in identity):
                row = self.studio.jobs(identity)
                return self.send(200, row) if row else self.send(404, {'error': '未找到作品。'})
            return self.send(404, {'error': '不存在的接口。'})
        assets = {'/': ('index.html', 'text/html; charset=utf-8'), '/app.js': ('app.js', 'text/javascript; charset=utf-8'), '/style.css': ('style.css', 'text/css; charset=utf-8')}
        if path not in assets:
            return self.send(404, {'error': '页面不存在。'})
        filename, content_type = assets[path]
        self.send(200, (ASSETS / filename).read_bytes(), content_type)

    def do_POST(self):
        try:
            length = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            return self.send(400, {'error': '请求格式无效。'})
        if not 0 < length <= 50000:
            return self.send(400, {'error': '请求内容过长或为空。'})
        raw_body = self.rfile.read(length)
        origin = self.headers.get('Origin')
        expected = {f'http://localhost:{self.server.server_port}', f'http://127.0.0.1:{self.server.server_port}'}
        session = self.session()
        if (not self.valid_host() or not session or (origin is not None and origin not in expected)
                or not secrets.compare_digest(self.headers.get('X-CSRF-Token', ''), self.studio.tokens.get(session, 'invalid'))):
            return self.send(403, {'error': '请求未通过本机会话校验，请刷新网页。'})
        if self.path != '/api/jobs':
            return self.send(404, {'error': '不存在的接口。'})
        try:
            if not 0 < length <= 50000 or self.headers.get_content_type() != 'application/json':
                raise ValueError()
            data = json.loads(raw_body)
            if not isinstance(data, dict):
                raise ValueError()
            prompt, genre, preference = data.get('prompt'), data.get('genre', 'auto'), data.get('preference', '')
            if not isinstance(prompt, str) or not 2 <= len(prompt.strip()) <= 10000 or not isinstance(preference, str) or len(preference) > 2000:
                raise ValueError()
            if genre not in ('auto', 'modern', 'wujue', 'qijue', 'wulv', 'qilv', 'ci'):
                raise ValueError()
            previous = data.get('previous')
            if previous is not None:
                from poetry_agent.core import Poem
                previous = {'title': Poem.parse(json.dumps(previous)).title, 'lines': Poem.parse(json.dumps(previous)).lines}
                if len(json.dumps(previous)) > 15000:
                    raise ValueError()
            identity = self.studio.add({'prompt': prompt.strip(), 'genre': genre, 'preference': preference, 'previous': previous})
            self.send(202, {'id': identity})
        except OverflowError as error:
            self.send(429, {'error': str(error)})
        except (ValueError, TypeError, KeyError, UnicodeError):
            self.send(400, {'error': '请填写完整样题，并检查输入长度。'})


def make_server(port=8765, database=None, runner=run_studio):
    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    server.studio = Studio(database or ROOT / 'var/studio.sqlite3', runner)
    return server


def main():
    parser = argparse.ArgumentParser(description='VERSEFORGE 本地创作台')
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    load_env(ROOT / '.env')
    server = make_server(args.port)
    print(f'VERSEFORGE http://127.0.0.1:{server.server_port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        server.studio.pool.shutdown(wait=False, cancel_futures=True)


if __name__ == '__main__':
    main()
