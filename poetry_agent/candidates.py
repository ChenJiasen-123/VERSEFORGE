"""Optional independent candidate runs sharing one wall-clock budget."""
import time
from dataclasses import asdict
from .core import compose
from .aesthetics import compare, failure_code


def compose_candidates(task, client, count=1, max_revisions=2, budget=120,
                       aesthetic=False, revision_scope='local'):
    if type(count) is not int or not 1 <= count <= 3:
        raise ValueError('候选数须为1—3的整数')
    if not 0 < budget <= 600:
        raise ValueError('时间预算须大于0且不超过600秒')
    if count == 1:
        return compose(task, client, max_revisions, budget, aesthetic, revision_scope)
    started = time.monotonic()
    runs = []
    selections = []
    for index in range(count):
        remaining = budget - (time.monotonic() - started)
        if remaining <= 0:
            break
        # Reserve part of the shared budget for comparison; no added retries.
        allocation = remaining * 0.8 / (count - index)
        try:
            runs.append(compose(task, client, max_revisions, allocation, aesthetic, revision_scope))
        except RuntimeError:
            if not runs:
                raise
            selections.append({'candidate': index + 1, 'error': 'generation_failed'})
            break
    if not runs:
        raise RuntimeError('预算耗尽，未生成候选')
    valid = [(i, r) for i, r in enumerate(runs) if r['poem']]
    best = min(valid, key=lambda x: len(x[1]['issues'])) if valid else (0, runs[0])
    for index, run in valid:
        if index == best[0] or len(run['issues']) != len(best[1]['issues']) or client.mock:
            continue
        remaining = budget - (time.monotonic() - started)
        if remaining <= 0:
            break
        record = {'a_candidate': best[0] + 1, 'b_candidate': index + 1}
        try:
            record.update(compare(best[1]['poem'], run['poem'], asdict(task), client, remaining))
            if record['assessment']['choice'] == 'b':
                best = (index, run)
        except (ValueError, RuntimeError, KeyError, TypeError) as exc:
            record['failure_code'] = failure_code(exc)
        selections.append(record)
    result = dict(best[1])
    result.update(candidate_runs=runs, candidate_selection=selections,
                  selected_candidate=best[0] + 1, requested_candidates=count,
                  elapsed_seconds=round(time.monotonic() - started, 3))
    return result
