"""Experimental CLI: produce checked line-repair options from an existing run."""
import argparse
import hashlib
import json
from pathlib import Path
from poetry_agent.client import DeepSeekClient, load_env
from poetry_agent.core import Task
from poetry_agent.aesthetics import failure_code
from poetry_agent.line_repairs import propose_line_repairs

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description='句级格律候选实验，不自动替换原稿')
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--include-unknown', action='store_true')
    parser.add_argument('--budget', type=int, default=90)
    parser.add_argument('--thinking', choices=['enabled', 'disabled'], default='disabled')
    parser.add_argument('--max-tokens', type=int, choices=[4096, 8192, 16384], default=4096)
    args = parser.parse_args()
    # Reserve the output before incurring API charges; never overwrite a result.
    with args.output.open('x', encoding='utf-8') as stream:
        source_hash = None
        model = None
        try:
            raw = args.run.read_bytes()
            source_hash = hashlib.sha256(raw).hexdigest()
            source = json.loads(raw)
            load_env(ROOT / '.env')
            client = DeepSeekClient()
            model = client.model
            result = propose_line_repairs(source['poem'], Task(**source['task']), client,
                                          budget=args.budget, include_unknown=args.include_unknown,
                                          thinking=args.thinking, max_tokens=args.max_tokens)
        except (ValueError, RuntimeError, TypeError, KeyError, OSError) as error:
            result = {'status': 'proposal_failed', 'failure_code': failure_code(error)}
        result['source_run'] = args.run.as_posix()
        result['source_sha256'] = source_hash
        result['model'] = model
        result['requested_settings'] = {'thinking': args.thinking, 'max_tokens': args.max_tokens,
                                        'budget': args.budget, 'include_unknown': args.include_unknown}
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(result['status'])
    print('Checked candidates: ' + str(len(result.get('candidates', []))))
    print('Pending context candidates: ' + str(result.get('pending_context_count', 0)))
    return 0 if result['status'] in ('checked_options_available', 'no_requested_repairs') else 2


if __name__ == '__main__':
    raise SystemExit(main())
