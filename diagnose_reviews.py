"""Small text-only diagnostic runner. Never auto-labels literary quality."""
import argparse
import json
from pathlib import Path
from uuid import uuid4
from poetry_agent.client import load_env, DeepSeekClient
from poetry_agent.aesthetics import review, failure_code

ROOT = Path(__file__).parent


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--live', action='store_true', help='Call the configured API')
    parser.add_argument('--cases', type=Path, default=ROOT / 'examples/review-probes.json')
    args = parser.parse_args()
    cases = json.loads(args.cases.read_text(encoding='utf-8'))['cases']
    if not args.live:
        print(json.dumps({'cases': len(cases), 'api_called': False, 'quality_labels_assigned': False}))
    else:
        load_env(ROOT / '.env')
        client = DeepSeekClient()
        path = ROOT / 'runs' / ('review-probes-' + uuid4().hex + '.json')
        rows = []
        for case in cases:
            try:
                # Do not show the diagnostic question to the reviewer.
                result = review(case['poem'], case['task'], client, 60)
            except (ValueError, RuntimeError, KeyError, TypeError) as exc:
                result = {'failure_code': failure_code(exc)}
            rows.append({'case': case, 'result': result, 'independent_quality_verdict': None})
            path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
        print(path)
