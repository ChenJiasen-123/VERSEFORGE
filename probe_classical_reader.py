"""Fixed-input diagnostic: reread existing anonymous poems without regenerating them."""
import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path

from classical_agent import resolve_reader_evidence
from experiments.classical_evolution.protocol import validate_reviews
from experiments.classical_evolution.store import RecordedClient, RunStore, digest
from poetry_agent.client import DeepSeekClient, load_env

ROOT = Path(__file__).resolve().parent


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser()
    parser.add_argument('--job', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--thinking', choices=['enabled', 'disabled'], default='enabled')
    parser.add_argument('--max-tokens', type=int, default=14000)
    parser.add_argument('--limit', type=int, choices=[1, 2, 3, 6, 9], default=9)
    args = parser.parse_args()
    cached = json.loads((args.job / 'calls/kernel-read-final-archive.json').read_text(encoding='utf-8'))
    request = copy.deepcopy(cached['request'])
    request['user']['poems'] = request['user']['poems'][:args.limit]
    data = request['user']
    passages = {p['id']: p['poem_passages'] for p in data['poems']}

    def validate(value):
        normalized = json.loads(resolve_reader_evidence(json.dumps(value, ensure_ascii=False), passages))
        return validate_reviews(normalized, data['poems'], data['requirements'], data['sources'])

    binding = {'role': 'fixed anonymous input reader diagnostic, not a poetry generation benchmark',
               'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               'input_request_sha256': digest(request), 'model': request['model'],
               'thinking': args.thinking, 'max_tokens': args.max_tokens,
               'selection': f'first {args.limit} poems in the recorded anonymous input; no poem-specific instruction',
               'original_call': str((args.job / 'calls/kernel-read-final-archive.json').resolve()),
               'interpretation_limit': 'One fixed case cannot establish general improvement. No old review, author plan or expected criticism is sent to the model.'}
    store = RunStore(args.out, binding)
    if store.load('result.json'):
        print('diagnostic already terminal; no repeated calls')
        return
    load_env(ROOT.parent / 'poetry-agent/.env')
    api = RecordedClient(DeepSeekClient(model=request['model']), store, seconds=240, max_calls=3)
    try:
        reviews = api.json('fixed-poems-read', request['system'], data, validate,
                           thinking=args.thinking, max_tokens=args.max_tokens)
        try:
            old = json.loads(cached['response']['content'])
            wanted = {p['id'] for p in data['poems']}
            old['reviews'] = [r for r in old['reviews'] if r['id'] in wanted]
            baseline = validate(old)
        except (ValueError, KeyError, TypeError):
            baseline = {}
        rows = [{'id': p['id'], 'poem': p['poem'], 'original_review': baseline.get(p['id']),
                 'diagnostic_review': reviews[p['id']]} for p in data['poems']]
        result = {'status': 'complete', 'rows': rows, 'budget': api.summary(),
                  'scope': binding['interpretation_limit']}
    except (ValueError, KeyError, TypeError, RuntimeError) as exc:
        result = {'status': 'incomplete', 'error_type': type(exc).__name__, 'budget': api.summary(),
                  'scope': binding['interpretation_limit']}
    store.save('result.json', result)
    print(json.dumps({k: v for k, v in result.items() if k != 'rows'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
