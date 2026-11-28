"""Separately registered fresh-prompt validation; author sees no gold task metadata."""
import argparse, concurrent.futures, hashlib, json, sys
from pathlib import Path
import classical_agent
from experiments.classical_evolution.engine import DEFAULT_CONFIG
from experiments.classical_evolution.store import code_digest, digest
from poetry_agent.client import DeepSeekClient, load_env
from poetry_agent.style.corpus import write as atomic_write

ROOT=Path(__file__).resolve().parent

def register(topics_file,directory):
    topics=json.loads(topics_file.read_text(encoding='utf-8'))
    original=json.loads((ROOT/'experiments/classical_evolution/topics.json').read_text(encoding='utf-8'))
    if not isinstance(topics,list) or len(topics)!=12:raise ValueError('exactly twelve fresh topics required')
    if len({t['id'] for t in topics})!=12 or len({t['prompt'] for t in topics})!=12:
        raise ValueError('duplicate fresh topic id or prompt')
    if {t['prompt'] for t in topics}&{t['prompt'] for t in original}:
        raise ValueError('old exposed prompts cannot be fresh validation')
    for t in topics:
        if t['split']!='held_out' or t['task']['genre'] not in ('wujue','qijue'):
            raise ValueError('this registered study covers five/seven-character quatrains only')
        if type(t.get('allusion_required')) is not bool or not t.get('requirements'):
            raise ValueError('missing evaluation metadata')
    sources=json.loads((ROOT/'experiments/classical_evolution/sources.json').read_text(encoding='utf-8'))
    knowledge=json.loads((ROOT/'experiments/classical_expression/knowledge.json').read_text(encoding='utf-8'))
    jobs=[{'key':f"{t['id']}-r{rep}-raw_classical_evolution",'topic_id':t['id'],
        'repetition':rep,'arm':'raw_classical_evolution'} for rep in (1,2) for t in topics]
    binding={'protocol':classical_agent.VERSION,'role':'fresh raw-prompt validation after exposed first study',
        'topics':topics,'sources':sources,'arms':['raw_classical_evolution'],'jobs':jobs,
        'model':'deepseek-reasoner','config':DEFAULT_CONFIG,'code_sha256':code_digest(),
        'entry_source_sha256':hashlib.sha256((ROOT/'classical_agent.py').read_bytes()).hexdigest(),
        'driver_source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'topics_file_sha256':hashlib.sha256(topics_file.read_bytes()).hexdigest(),
        'poetics_sha256':digest(knowledge),'critic_policy':classical_agent.CRITIC_POLICY,
        'creation_inputs':'original prompt + auto hint + full verified library only; all task/requirements metadata are evaluation-only',
        'previous_study':'classical-evolution-combined-02; frozen results and failures retained',
        'acceptance':'original 22/24 known-hard-clear and topic-supported, 18/24 worth keeping, every submitted required allusion independently read; unresolved readings separate',
        'limits':'Same source families, fresh situations; not unseen-source generalization or an equal-compute genetic-operator ablation.'}
    binding['experiment_sha256']=digest(binding)
    directory.mkdir(parents=True,exist_ok=True);path=directory/'experiment-binding.json'
    if path.exists():
        if json.loads(path.read_text(encoding='utf-8'))!=binding:raise ValueError('study binding changed; use a new directory')
    else:
        if any(directory.iterdir()):raise ValueError('refusing nonempty unbound directory')
        atomic_write(path,binding)
    return binding

def execute_job(binding,directory,job,client):
    folder=directory/'jobs'/job['key']
    if (folder/'result.json').exists():return
    topic=next(t for t in binding['topics'] if t['id']==job['topic_id'])
    progress=lambda s:print(job['key'],s,flush=True)
    result=classical_agent.run_raw(topic['prompt'],folder,client,hint='auto',
        library=binding['sources'],config=binding['config'],progress=progress)
    progress('terminal-'+result['status'])

def main():
    sys.stdout.reconfigure(encoding='utf-8')
    p=argparse.ArgumentParser();p.add_argument('--topics',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True);p.add_argument('--prepare-only',action='store_true')
    p.add_argument('--workers',type=int,choices=[1,2,3,4],default=4);a=p.parse_args()
    binding=register(a.topics,a.out)
    if a.prepare_only:print('registered_fresh_runs',len(binding['jobs']));return
    load_env(ROOT.parent/'poetry-agent'/'.env');errors=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=a.workers) as pool:
        futures={pool.submit(execute_job,binding,a.out,j,DeepSeekClient(model=binding['model'])):j for j in binding['jobs']}
        for f in concurrent.futures.as_completed(futures):
            try:f.result()
            except Exception as exc:errors.append({'job':futures[f]['key'],'error_type':type(exc).__name__})
    if errors:atomic_write(a.out/'driver-failures.json',errors)
    print('terminal_fresh_runs',len(list((a.out/'jobs').glob('*/result.json'))),'/',len(binding['jobs']),flush=True)

if __name__=='__main__':main()
