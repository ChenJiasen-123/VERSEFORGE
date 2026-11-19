"""Paired workflow evaluation; blind packets contain no automatic quality labels."""
import argparse
import json
import random
from pathlib import Path
from uuid import uuid4

from poetry_agent.client import DeepSeekClient, MockClient, load_env
from poetry_agent.core import Task, compose

ROOT = Path(__file__).resolve().parent
TASKS = [
    Task('换班后的清晨', required_words=['灯'], extra_requirements='现代诗；允许明亮与疲惫并存，不虚构具体工厂史。'),
    Task('一次没有解决的告别', extra_requirements='可直接抒情，不强制反转或具体物件结尾。'),
    Task('发现日常中的可笑之处', extra_requirements='轻快或幽默；不把他人的困境当笑料。'),
    Task('邀请陌生人一起看江', extra_requirements='写现代诗；包含明确邀请，不虚构真实景点掌故。'),
]


def run(client, folder, count=1, budget=120, *, tasks=None, max_revisions=2, generation_thinking=None):
    tasks = TASKS if tasks is None else tasks
    if not isinstance(tasks, (list, tuple)) or not 1 <= len(tasks) <= 4 or any(not isinstance(t, Task) for t in tasks):
        raise ValueError('tasks must contain 1 to 4 Task objects')
    if type(count) is not int or not 1 <= count <= len(tasks):
        raise ValueError('count exceeds supplied tasks')
    if type(max_revisions) is not int or not 0 <= max_revisions <= 2:
        raise ValueError('max_revisions must be 0 to 2')
    if generation_thinking not in (None, 'enabled', 'disabled'):
        raise ValueError('invalid generation thinking mode')
    if isinstance(budget, bool) or not isinstance(budget, (int, float)) or not 0 < budget <= 600:
        raise ValueError('invalid per-arm budget')
    folder.mkdir(parents=True, exist_ok=False)
    mapping, records, blind = [], [], []
    rng = random.SystemRandom()
    for index, task in enumerate(tasks[:count], 1):
        pair = []
        arms = ['baseline', 'aesthetic']
        rng.shuffle(arms)
        for arm in arms:
            token = uuid4().hex[:12]
            try:
                result = compose(task, client, max_revisions=max_revisions, budget=budget, aesthetic=arm == 'aesthetic',
                                 generation_thinking=generation_thinking)
                record = {'sample_id': token, 'arm': arm, 'pair': index, 'result': result}
            except RuntimeError:
                # Never persist exception text, which may contain provider details.
                result = None
                record = {'sample_id': token, 'arm': arm, 'pair': index, 'error': 'generation_failed'}
            records.append(record)
            record['experiment_settings'] = {'max_revisions': max_revisions,
                'generation_thinking': generation_thinking or 'service_default', 'per_arm_budget': budget}
            mapping.append({'pair': index, 'sample_id': token, 'arm': arm})
            if result and result['poem']:
                pair.append({'sample_id': token, 'poem': result['poem']})
            for name, data in [('raw.json', records), ('mapping.json', mapping)]:
                (folder / name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        if len(pair) != 2:
            continue
        rng.shuffle(pair)
        blind.append({'pair': index, 'task': task.__dict__, 'samples': pair,
                      'judgment': {'preference': None, 'text_evidence': '', 'tradeoff': '',
                                   'audio_reviewed': False, 'listener_notes': ''}})
        # Checkpoint after every complete pair. Raw data is separate from the blind packet.
        for name, data in [('raw.json', records), ('mapping.json', mapping), ('blind.json', blind)]:
            (folder / name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    (folder / 'README.txt').write_text(
        'Blind review: open blind.json only. Keep mapping.json and raw.json hidden from raters.\n' +
        ('With max_revisions=0, arms compare generation prompts only; no review or selection calls.\n'
         if max_revisions == 0 else 'Arms compare entire workflows, not just prompts; cost and call counts differ.\n') +
        'One draw per arm is exploratory, not statistical proof. Mock outputs cannot show quality gains.\n'
        'Generation order and A/B placement are randomized; authorship may still be recognizable.\n'
        'Incomplete pairs remain in raw.json and mapping.json, excluded from blind.json.\n'
        'No ratings or training labels have been inferred. Audio has not been reviewed.\n', encoding='utf-8')
    if not (folder / 'blind.json').exists():
        (folder / 'blind.json').write_text('[]', encoding='utf-8')
    return folder


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--mock', action='store_true')
    parser.add_argument('--count', type=int, choices=range(1, 5), default=1)
    parser.add_argument('--budget', type=int, choices=range(1, 601), default=120)
    parser.add_argument('--tasks-file', type=Path, help='JSON array of 1 to 4 task objects')
    parser.add_argument('--max-revisions', type=int, choices=range(3), default=2)
    parser.add_argument('--generation-thinking', choices=['enabled', 'disabled'])
    args = parser.parse_args()
    load_env(ROOT / '.env')
    client = MockClient() if args.mock else DeepSeekClient()
    tasks = [Task(**t) for t in json.loads(args.tasks_file.read_text(encoding='utf-8-sig'))] if args.tasks_file else None
    output = run(client, ROOT / 'runs' / ('evaluation-' + uuid4().hex), args.count, args.budget,
                 tasks=tasks, max_revisions=args.max_revisions, generation_thinking=args.generation_thinking)
    print(output)
