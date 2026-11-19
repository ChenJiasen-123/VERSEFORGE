"""Four real generation/repair diagnostics; no automatic context disambiguation."""
import json
from pathlib import Path
from poetry_agent.client import DeepSeekClient, load_env
from poetry_agent.core import Task, compose
from poetry_agent.aesthetics import failure_code

PROFILES = ['ping_rhyme', 'ping_no_rhyme', 'ze_rhyme', 'ze_no_rhyme']

if __name__ == '__main__':
    folder = Path('runs/wujue-matrix-trial-01')
    if folder.exists(): raise SystemExit('existing trial will not be overwritten')
    folder.mkdir(parents=True)
    load_env('.env')
    client = DeepSeekClient()
    for profile in PROFILES:
        task = Task(topic='雨夜候人', genre='wujue', wujue_pattern=profile,
                    extra_requirements='意脉连贯，不为凑韵制造生硬措辞。')
        try:
            result = compose(task, client, max_revisions=1, budget=100,
                             aesthetic=False, generation_thinking='disabled')
        except Exception as error:
            result = {'failure_code': failure_code(error), 'profile': profile}
        result['experiment'] = {'kind': 'one_task_per_exact_basic_profile',
                                'topic_held_constant': True, 'literary_review_enabled': False,
                                'context_readings_supplied': False, 'quality_verified': False}
        with (folder / (profile + '.json')).open('x', encoding='utf-8') as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)
        print('saved ' + profile, flush=True)
