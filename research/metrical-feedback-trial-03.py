"""Matched saved seeds; one real repair per feedback arm, all outcomes retained."""
import hashlib
import json
import random
from pathlib import Path
from poetry_agent.client import DeepSeekClient, load_env
from poetry_agent.core import Task, compose
from poetry_agent.aesthetics import failure_code

if __name__ == '__main__':
    folder = Path('runs/metrical-feedback-trial-03')
    if folder.exists(): raise SystemExit('existing trial will not be overwritten')
    folder.mkdir(parents=True)
    load_env('.env')
    live = DeepSeekClient()
    rng = random.Random(20261119)
    for profile in ('ze_rhyme', 'ping_rhyme'):
        source = Path('runs/wujue-matrix-trial-01') / (profile + '.json')
        raw = source.read_bytes()
        data = json.loads(raw)
        seed = data['history'][-1]['poem']
        order = ['previous', 'line_targets']
        rng.shuffle(order)
        for arm in order:
            class SeedThenRepair:
                mock = False
                model = live.model
                def __init__(self): self.calls = []
                def complete(self, system, user, **kwargs):
                    if not self.calls:
                        self.calls.append({'source': 'saved_seed'})
                        return {'content': json.dumps(seed, ensure_ascii=False), 'usage': {}}
                    payload = json.loads(user)
                    feedback = payload['revision']['metrical_feedback']
                    if arm == 'previous':
                        for key in ('feedback_protocol', 'line_targets', 'rhyme_lines_1based'):
                            feedback.pop(key, None)
                    self.calls.append({'source': 'live_repair', 'feedback_sent': feedback})
                    return live.complete(system, json.dumps(payload, ensure_ascii=False), **kwargs)

            client = SeedThenRepair()
            try:
                result = compose(Task(**data['task']), client, max_revisions=1, budget=60,
                                 aesthetic=False, generation_thinking='disabled')
            except Exception as error:
                result = {'failure_code': failure_code(error)}
            result['experiment'] = {'kind': 'saved_seed_single_live_repair', 'arm': arm,
                                    'order_for_profile': order, 'order_seed': 20261119,
                                    'source': source.as_posix(), 'source_sha256': hashlib.sha256(raw).hexdigest(),
                                    'calls': client.calls, 'quality_verified': False}
            with (folder / f'{profile}-{arm}.json').open('x', encoding='utf-8') as stream:
                json.dump(result, stream, ensure_ascii=False, indent=2)
            print('saved ' + profile + ' ' + arm, flush=True)
