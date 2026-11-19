"""Replay saved draft/review, then make at most two live calls with new limits."""
import json
from pathlib import Path
from poetry_agent.client import DeepSeekClient, load_env
from poetry_agent.core import Task, compose

if __name__ == '__main__':
    source = Path('runs/modern-workflow-trial-03/02.json')
    output = Path('runs/local-revision-replay-01.json')
    if output.exists(): raise SystemExit('output exists')
    data = json.loads(source.read_text(encoding='utf-8'))
    anchor = data['history'][0]
    load_env('.env')
    live = DeepSeekClient()

    class ReplayThenLive:
        mock = False
        model = live.model
        def __init__(self): self.trace = []
        def complete(self, system, user, **kwargs):
            payload = json.loads(user)
            if not self.trace:
                assert 'revision' not in payload
                self.trace.append({'source': 'saved_initial_draft'})
                return {'content': json.dumps(anchor['poem'], ensure_ascii=False), 'usage': {}}
            if len(self.trace) == 1:
                assert 'text_structure' in payload
                self.trace.append({'source': 'saved_initial_review'})
                return {'content': json.dumps(anchor['aesthetic_review']['assessment'], ensure_ascii=False), 'usage': {}}
            self.trace.append({'source': 'live', 'revision_limits': payload.get('revision_limits')})
            return live.complete(system, user, **kwargs)

    client = ReplayThenLive()
    result = compose(Task(**data['task']), client, max_revisions=1, budget=110,
                     aesthetic=True, generation_thinking='disabled')
    result['experiment_kind'] = 'mixed_saved_input_and_live_revision_not_fresh_end_to_end'
    result['replayed_source'] = source.as_posix()
    result['call_trace'] = client.trace
    result['human_preference'] = None
    with output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print('Saved explicit replay/live diagnostic.')
