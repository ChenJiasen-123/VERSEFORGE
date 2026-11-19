"""Propose one whole classical-poem revision from a saved run."""
import argparse
import hashlib
import json
from pathlib import Path
from poetry_agent.client import DeepSeekClient, load_env
from poetry_agent.core import Task
from poetry_agent.aesthetics import failure_code
from poetry_agent.whole_repairs import propose_whole_repair


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--feedback-file', type=Path)
    parser.add_argument('--budget', type=int, default=90)
    parser.add_argument('--thinking', choices=['enabled', 'disabled'], default='enabled')
    parser.add_argument('--max-tokens', type=int, choices=[4096, 8192, 16384], default=8192)
    args = parser.parse_args()
    with args.output.open('x', encoding='utf-8') as file:
        record = {'source_run': args.run.as_posix()}
        try:
            raw = args.run.read_bytes()
            record['source_sha256'] = hashlib.sha256(raw).hexdigest()
            source = json.loads(raw)
            if 'poem' not in source and isinstance(source.get('result'), dict):
                source = source['result']
            note = args.feedback_file.read_text(encoding='utf-8-sig') if args.feedback_file else ''
            load_env(Path(__file__).resolve().parent / '.env')
            record.update(propose_whole_repair(source['poem'], Task(**source['task']), DeepSeekClient(),
                note=note, budget=args.budget, thinking=args.thinking, max_tokens=args.max_tokens))
        except (ValueError, RuntimeError, KeyError, TypeError, OSError) as error:
            record.update(status='proposal_failed', failure_code=failure_code(error))
        json.dump(record, file, ensure_ascii=False, indent=2)
    print(record['status'])
    return 0 if record['status'] == 'proposal_checked' else 2


if __name__ == '__main__':
    raise SystemExit(main())
