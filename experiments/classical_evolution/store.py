"""Bound run identities, atomic checkpoints and credential-free model ledgers."""
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from poetry_agent.style.corpus import write as atomic_write
from poetry_agent.aesthetics import failure_code
from .protocol import dumps


def digest(obj):
    return hashlib.sha256(dumps(obj).encode()).hexdigest()


def code_digest():
    root = Path(__file__).resolve().parents[2]
    paths = list((root/'experiments/classical_evolution').glob('*.py'))
    paths += list((root/'experiments/evolution').glob('*.py'))
    # Include the baseline studio/editor and all their rule dependencies too.
    paths += list((root/'poetry_agent').glob('*.py'))
    paths += list((root/'poetry_agent/data').glob('*.json'))
    return digest({str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)})


class RunStore:
    def __init__(self, directory, binding):
        self.path = Path(directory)
        self.path.mkdir(parents=True, exist_ok=True)
        self.binding = binding
        self.binding_hash = digest(binding)
        path = self.path/'binding.json'
        if path.exists():
            if json.loads(path.read_text(encoding='utf-8')) != binding:
                raise ValueError('run binding changed; use a new output directory')
        elif any(self.path.iterdir()):
            raise ValueError('refusing to adopt an unbound nonempty run directory')
        else:
            atomic_write(path, binding)

    def save(self, name, obj):
        atomic_write(self.path/name, obj)

    def load(self, name):
        p = self.path/name
        return json.loads(p.read_text(encoding='utf-8')) if p.exists() else None

    def event(self, kind, **fields):
        with (self.path/'events.jsonl').open('a', encoding='utf-8') as f:
            f.write(dumps({'event':kind, 'utc':datetime.now(timezone.utc).isoformat(), **fields})+'\n')


class RecordedClient:
    """Per-action response caching. Different benchmark repetitions have distinct stores.

    A terminal cache record is never silently overwritten. A process lost during
    an outstanding network call may have incurred an unrecorded provider charge;
    that unavoidable boundary is not represented as a known zero-cost call.
    """
    mock = False

    def __init__(self, client, store, *, seconds=900, max_calls=45, generation_tokens=16384, progress=lambda _: None):
        self.client, self.store = client, store
        self.model = client.model
        self.mock = getattr(client, 'mock', False)
        self.started = time.monotonic()
        self.seconds, self.max_calls, self.progress = seconds, max_calls, progress
        self.generation_tokens = generation_tokens
        rows = store.load('call-ledger.json') or []
        self.ledger = rows
        self.previous_elapsed = sum(r['elapsed_seconds'] for r in rows)

    def summary(self):
        actual = [r for r in self.ledger if r.get('attempted')]
        return {'calls':len(actual), 'max_calls':self.max_calls,
                'elapsed_seconds':round(self.previous_elapsed+time.monotonic()-self.started, 3),
                'budget_seconds':self.seconds,
                'tokens':sum(int((r.get('usage') or {}).get('total_tokens') or 0) for r in actual),
                'usage_known_calls':sum(bool(r.get('usage')) for r in actual),
                'usage_unknown_calls':sum(not bool(r.get('usage')) for r in actual),
                'exhausted':len(actual)>=self.max_calls or self.previous_elapsed+time.monotonic()-self.started>=self.seconds}

    def call(self, action, system, payload, *, thinking='disabled', max_tokens=6000):
        settings = {'thinking':thinking, 'max_tokens':max_tokens}
        request = {'system':system, 'user':payload, 'settings':settings, 'model':self.model}
        key = digest(request)
        cache_name = 'calls/'+action+'.json'
        cached = self.store.load(cache_name)
        if cached:
            if cached['request_sha256'] != key:
                raise ValueError('cached action has different inputs')
            if cached.get('error'):
                raise RuntimeError(cached['error'])
            return cached['response']
        summary = self.summary()
        if summary['exhausted']:
            raise RuntimeError('classical evolution budget exhausted')
        self.progress(action)
        self.store.event('call_started', action=action, request_sha256=key)
        start = time.monotonic()
        record = {'action':action, 'request_sha256':key, 'attempted':True}
        try:
            response = self.client.complete(system, dumps(payload),
                timeout=min(90, self.seconds-summary['elapsed_seconds']), **settings)
            # Explicit whitelist: do not serialize credentials, headers or raw exceptions.
            clean = {k:response[k] for k in ('content','usage','request_settings') if k in response}
            meta = response.get('response_metadata') or {}
            clean['provider'] = {k:meta[k] for k in ('id','model','created','started_utc','base_url') if k in meta}
            record['usage'] = response.get('usage', {})
            self.store.save(cache_name, {'request_sha256':key, 'request':request, 'response':clean})
            return clean
        except (ValueError, RuntimeError, OSError) as exc:
            record['failed'] = True
            record['failure_code'] = failure_code(exc)
            self.store.save(cache_name, {'request_sha256':key, 'error':'provider_call_failed',
                                        'failure_code':record['failure_code']})
            raise RuntimeError('provider_call_failed') from None
        finally:
            record['elapsed_seconds'] = round(time.monotonic()-start, 3)
            self.ledger.append(record)
            self.store.save('call-ledger.json', self.ledger)
            self.store.event('call_finished', action=action, failed=record.get('failed', False))

    def json(self, action, system, payload, validator, *, thinking='disabled', max_tokens=6000):
        """One explicit structure repair; both original and repair remain recorded."""
        raw = self.call(action, system, payload, thinking=thinking, max_tokens=max_tokens)
        try:
            return validator(json.loads(raw['content']))
        except (ValueError, TypeError, KeyError) as exc:
            # These are local validator/JSON-parser messages, never transport exceptions.
            repaired = self.call(action+'-schema-repair', system+'\n上次返回结构或原文引证无效。按原协议重新输出，核对每个id及单行原文引文。',
                                 {'original_input':payload, 'invalid_output':raw['content'],
                                  'validation_error':str(exc)[:200]},
                                 thinking='disabled', max_tokens=max_tokens)
            return validator(json.loads(repaired['content']))

    def complete(self, system, user, **kwargs):
        """Adapter for existing studio baseline and symmetric comparison."""
        counter = getattr(self, '_adapter_counter', 0)+1
        self._adapter_counter = counter
        return self.call(f'adapter-{counter:03d}', system, json.loads(user),
                         thinking=kwargs.get('thinking') or 'disabled',
                         max_tokens=min(kwargs.get('max_tokens', self.generation_tokens), self.generation_tokens))
