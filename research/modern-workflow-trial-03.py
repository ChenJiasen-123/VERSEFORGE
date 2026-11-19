"""Two end-to-end text diagnostics. Run from project root with PYTHONPATH=."""
import json
from pathlib import Path
from poetry_agent.client import DeepSeekClient, load_env
from poetry_agent.core import Task, compose
from poetry_agent.aesthetics import failure_code

TASKS = [
    Task(topic="电梯停在两层之间", max_lines=12,
         extra_requirements="写一首独立的现代诗。人物、视角、语言强度自定，不必安排获救或人生道理。"),
    Task(topic="毕业典礼结束后，空操场上的一次呼喊", max_lines=12,
         extra_requirements="写一首独立的现代诗。可以呼告、直接抒情或使用反复，也可以另选写法；不必写成低声独白。"),
]

if __name__ == '__main__':
    folder = Path('runs/modern-workflow-trial-03')
    if folder.exists(): raise SystemExit('existing trial will not be overwritten')
    folder.mkdir(parents=True)
    load_env('.env')
    client = DeepSeekClient()
    for number, task in enumerate(TASKS, 1):
        try:
            result = compose(task, client, max_revisions=1, budget=110,
                             aesthetic=True, generation_thinking='disabled')
        except Exception as error:
            result = {'failure_code': failure_code(error), 'topic': task.topic}
        with (folder / f'{number:02}.json').open('x', encoding='utf-8') as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)
        print(f'saved diagnostic {number}', flush=True)
