"""Offline exact-poem review. No API calls and no silent record overwrite."""
import argparse
import hashlib
import json
import sys
from pathlib import Path
from poetry_agent.context_review import apply_review


def review_files(run_path, ledger_path, output_path):
    run_bytes, ledger_bytes = run_path.read_bytes(), ledger_path.read_bytes()
    run, ledger = json.loads(run_bytes), json.loads(ledger_bytes)
    if run.get('task', {}).get('genre') != 'qijue' or not run['task'].get('qijue_pattern'):
        raise ValueError('当前入口仅复核已指定基本谱的七绝运行')
    if not run.get('poem'):
        raise ValueError('运行记录没有有效作品')
    result = apply_review(run['poem'], run['task']['qijue_pattern'], ledger)
    result.update(source_run=str(run_path), source_run_sha256=hashlib.sha256(run_bytes).hexdigest(),
                  reading_ledger=str(ledger_path), reading_ledger_sha256=hashlib.sha256(ledger_bytes).hexdigest())
    with output_path.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    return result


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='离线复核指定七绝基本谱，不调用模型')
    parser.add_argument('--run', required=True, type=Path)
    parser.add_argument('--ledger', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    try:
        result = review_files(args.run, args.ledger, args.output)
    except (OSError, ValueError, KeyError, TypeError):
        print('复核未完成：请检查文件、字段、诗稿绑定及输出路径；已有文件不会覆盖。')
        return 1
    status = result['basic_target_check']['status']
    print('指定基本谱复核状态：' + status)
    print('范围仅限当前诗稿、复核表与所选基本谱，不认证文学质量或全部格律。')
    return 0 if status == 'pass' else 2


if __name__ == '__main__':
    raise SystemExit(main())
