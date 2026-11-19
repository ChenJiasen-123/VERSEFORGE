"""Start from saved poems; at most two real repair calls per selected profile."""
import hashlib
import json
from pathlib import Path
from poetry_agent.client import DeepSeekClient, load_env
from poetry_agent.core import Task, compose
from poetry_agent.aesthetics import failure_code

if __name__ == '__main__':
    folder = Path('runs/wujue-repair-trial-02')
    if folder.exists(): raise SystemExit('existing trial will not be overwritten')
    folder.mkdir(parents=True)
    load_env('.env')
    live = DeepSeekClient()
    for profile in ('ze_rhyme', 'ping_rhyme'):
        source = Path('runs/wujue-matrix-trial-01') / (profile + '.json')
        raw = source.read_bytes()
        saved = json.loads(raw)
        seed = saved['history'][-1]['poem']

        class SeedThenLive:
            mock = False
            model = live.model
            def __init__(self): self.trace = []
            def complete(self, system, user, **kwargs):
                payload = json.loads(user)
                if not self.trace:
                    self.trace.append({'source': 'saved_second_draft'})
                    return {'content': json.dumps(seed, ensure_ascii=False), 'usage': {}}
                self.trace.append({'source': 'live_repair',
                                   'feedback': payload.get('revision', {}).get('metrical_feedback')})
                return live.complete(system, user, **kwargs)

        client = SeedThenLive()
        try:
            result = compose(Task(**saved['task']), client, max_revisions=2,
                             budget=100, aesthetic=False, generation_thinking='disabled')
        except Exception as error:
            result = {'failure_code': failure_code(error)}
        result['experiment'] = {'kind': 'saved_seed_then_live_repairs',
                                'source': source.as_posix(), 'source_sha256': hashlib.sha256(raw).hexdigest(),
                                'calls': client.trace, 'quality_verified': False,
                                'context_readings_supplied': False}
        with (folder / (profile + '.json')).open('x', encoding='utf-8') as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)
        print('saved ' + profile, flush=True)
