"""CLI: one poem or resumable, preregistered paired benchmark."""
import argparse
import concurrent.futures
import hashlib
import json
import random
import sys
from dataclasses import asdict
from pathlib import Path

from poetry_agent.client import DeepSeekClient, load_env
from poetry_agent.studio import run_studio
from poetry_agent.style.corpus import write as atomic_write
from .engine import ClassicalEvolution, DEFAULT_CONFIG, make_task, known_checks, eligible, gates
from .protocol import VERSION, READER_SYSTEM, validate_reviews, dumps
from .store import RunStore, RecordedClient, code_digest, digest

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(__file__).resolve().parent


def load_data():
    return (json.loads((DATA/'topics.json').read_text(encoding='utf-8')),
            json.loads((DATA/'sources.json').read_text(encoding='utf-8')))


def baseline(topic, sources, client, directory, config, progress):
    """The current one-candidate studio + up to three editorial rounds, unchanged.

    Both arms see the same original topic, source cards, model, token ceiling,
    wall-clock and call ceilings. Actual calls/tokens are separately reported.
    """
    store=RunStore(directory,{'protocol':VERSION,'arm':'baseline_studio','code_sha256':code_digest(),
        'topic':topic,'sources':sources,'config':config,'model':client.model,'mode':'live'})
    result=store.load('result.json')
    if result:return result
    api=RecordedClient(client,store,seconds=config['seconds'],max_calls=config['max_calls'],
                       generation_tokens=config['generation_tokens'],progress=progress)
    try:
        task=make_task(topic)
        preference='资料仅供核对，不是新增题目要求。不要把仄起理解成押仄韵。指定基本谱：'+(
            task.qijue_pattern or task.wujue_pattern or task.lushi_pattern or task.ci_profile or '')
        preference+='\n给定可核典源：'+dumps(sources)
        workflow=run_studio(topic['prompt'],hint=task.genre,preference=preference,client=api,
            independent_editor=True,candidate_count=1,total_budget_seconds=config['seconds'],
            total_max_calls=config['max_calls'],style_mode='standard',expansion_mode='native_studio',
            progress=lambda p:progress('baseline-'+p))
        store.save('studio-workflow.json',workflow)
        poem=workflow.get('poem')
        selected=None
        if poem:
            candidate={'id':'c'+digest(poem)[:12],'poem':poem,'checks':known_checks(poem,task)}
            requirements={f'r{i+1}':r for i,r in enumerate(topic['requirements'])}
            payload={'original_prompt':topic['prompt'],'genre':task.genre,'requirements':requirements,
                'allusion_required':topic.get('allusion_required',False),'sources':sources,
                'poems':[{'id':candidate['id'],'poem':poem}]}
            reviews=api.json('baseline-independent-final-read',READER_SYSTEM,payload,
                lambda v:validate_reviews(v,[candidate],requirements,sources),max_tokens=6000)
            candidate['review']=reviews[candidate['id']]
            selected=candidate if eligible(candidate,topic) else None
        result={'protocol':VERSION,'arm':'baseline_studio','status':'candidate_ready' if selected else 'needs_review',
            'poem':selected['poem'] if selected else None,'selected':selected,
            'best_unfinished':candidate if poem and not selected else None,
            'completed_generations':None,'mode':'live','literary_quality_verified':False,'budget':api.summary()}
        if selected and gates(selected,topic)['meter_status']=='unknown':
            result['status']='candidate_with_unresolved_readings'
    except (ValueError,KeyError,TypeError,RuntimeError):
        result={'protocol':VERSION,'arm':'baseline_studio','status':'incomplete','poem':None,
            'mode':'live','budget':api.summary(),'literary_quality_verified':False}
    store.save('result.json',result)
    return result


def summarize(directory):
    directory=Path(directory)
    binding=json.loads((directory/'experiment-binding.json').read_text(encoding='utf-8'))
    observations=[]
    blind=[]
    mapping=[]
    for job in binding['jobs']:
        path=directory/'jobs'/job['key']/'result.json'
        if not path.exists():continue
        result=json.loads(path.read_text(encoding='utf-8'))
        candidate=result.get('selected') or result.get('best_unfinished')
        topic=next(t for t in binding['topics'] if t['id']==job['topic_id'])
        row={'job':job['key'],'topic':job['topic_id'],'repetition':job['repetition'],'arm':job['arm'],
             'status':result['status'],'budget':result.get('budget'),
             'has_selected_poem':bool(result.get('selected')),
             'completed_generations':result.get('completed_generations'),
             'formal_pass':bool(result.get('selected')) and gates(result['selected'],topic)['meter_status']=='pass',
             'unresolved_readings':bool(result.get('selected')) and gates(result['selected'],topic)['meter_status']=='unknown',
             'gates':gates(candidate,topic) if candidate else None,
             'model_literary_keep':bool(candidate) and (candidate.get('review') or {}).get('decision')=='keep'}
        observations.append(row)
        if candidate:
            blind_id=hashlib.sha256((binding['experiment_sha256']+job['key']).encode()).hexdigest()[:12]
            blind.append({'id':blind_id,'topic':topic['prompt'],'poem':candidate['poem']})
            mapping.append({'blind_id':blind_id,'job':job['key'],'arm':job['arm'],'selected':bool(result.get('selected'))})
    random.Random(binding['experiment_sha256']).shuffle(blind)
    atomic_write(directory/'observations.json',observations)
    atomic_write(directory/'blind-packet.json',blind)
    atomic_write(directory/'blind-mapping-private.json',mapping)
    lines=['古诗演化对照运行记录','',
           f"已记录 {len(observations)}/{len(binding['jobs'])} 次运行。模型审读不是用户偏好或文学质量认证。",'']
    for arm in binding['arms']:
        rs=[r for r in observations if r['arm']==arm]
        selected=sum(r['has_selected_poem'] for r in rs)
        formal=sum(r['formal_pass'] for r in rs)
        unknown=sum(r['unresolved_readings'] for r in rs)
        calls=sum((r['budget'] or {}).get('calls',0) for r in rs)
        tokens=sum((r['budget'] or {}).get('tokens',0) for r in rs)
        lines.append(f'{arm}: 已完成记录 {len(rs)}；可展示候选 {selected}；基本谱全确认 {formal}；仍待核音 {unknown}；调用 {calls}；已知tokens {tokens}。')
    lines+=['','作品盲读稿：','']
    for p in blind:
        lines += [p['id'],p['topic'],p['poem']['title'],*p['poem']['lines'],'']
    (directory/'作品与运行汇总.txt').write_text('\n'.join(lines),encoding='utf-8')
    return {'completed':len(observations),'expected':len(binding['jobs']),
            'all_terminal':len(observations)==len(binding['jobs'])}


def benchmark(args):
    topics,sources=load_data()
    selected=[t for t in topics if t['split']==args.split]
    config={**DEFAULT_CONFIG,'seconds':args.seconds,'max_calls':args.max_calls}
    arms=['baseline_studio','classical_evolution']
    jobs=[{'key':f"{t['id']}-r{rep}-{arm}",'topic_id':t['id'],'repetition':rep,'arm':arm}
          for rep in range(1,args.repetitions+1) for t in selected for arm in arms]
    binding={'protocol':VERSION,'code_sha256':code_digest(),'topics':selected,'sources':sources,
             'config':config,'arms':arms,'jobs':jobs,'model':args.model,'split':args.split}
    if args.split=='held_out':
        if not args.freeze:raise ValueError('held-out benchmark requires a frozen pilot manifest')
        freeze=json.loads(args.freeze.read_text(encoding='utf-8'))
        if freeze['code_sha256']!=binding['code_sha256'] or freeze['sources_sha256']!=digest(sources):
            raise ValueError('code or sources changed after freezing')
        if freeze['held_out_sha256']!=digest(selected) or freeze['config']!=config or freeze['model']!=args.model:
            raise ValueError('held-out/config/model changed after freezing')
        binding['freeze_sha256']=digest(freeze)
    binding['experiment_sha256']=digest(binding)
    args.out.mkdir(parents=True,exist_ok=True)
    path=args.out/'experiment-binding.json'
    if path.exists():
        if json.loads(path.read_text(encoding='utf-8'))!=binding:
            raise ValueError('benchmark changed; use a new output directory')
    else:
        if any(args.out.iterdir()):raise ValueError('nonempty unbound benchmark directory')
        atomic_write(path,binding)
    # Resume keeps the same declared jobs. Terminal failures remain in the denominator.
    def execute(job):
        directory=args.out/'jobs'/job['key']
        if (directory/'result.json').exists():return
        topic=next(t for t in selected if t['id']==job['topic_id'])
        cards={k:sources[k] for k in topic['source_ids']}
        progress=lambda action:print(job['key'],action,flush=True)
        progress('starting')
        client=DeepSeekClient(model=args.model)
        if job['arm']=='classical_evolution':
            r=ClassicalEvolution(topic,cards,client,directory,config=config,progress=progress).run()
        else:r=baseline(topic,cards,client,directory,config,progress)
        progress('terminal-'+r['status'])
    failures=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        fs={pool.submit(execute,j):j for j in jobs}
        for f in concurrent.futures.as_completed(fs):
            try:f.result()
            except Exception as exc:
                failures.append({'job':fs[f]['key'],'error_type':type(exc).__name__})
                print(fs[f]['key'],'driver-failed',type(exc).__name__,flush=True)
    if failures:atomic_write(args.out/'driver-failures.json',failures)
    print(dumps(summarize(args.out)),flush=True)


def main():
    for stream in (sys.stdout,sys.stderr):
        if hasattr(stream,'reconfigure'):stream.reconfigure(encoding='utf-8')
    p=argparse.ArgumentParser(description='古诗演化入口与固定题集对照')
    p.add_argument('--env-file',type=Path,default=ROOT.parent/'poetry-agent'/'.env')
    p.add_argument('--model',default='deepseek-reasoner')
    sub=p.add_subparsers(dest='command',required=True)
    b=sub.add_parser('benchmark');b.add_argument('--split',choices=['pilot','held_out'],required=True)
    b.add_argument('--out',type=Path,required=True);b.add_argument('--repetitions',type=int,choices=[1,2],default=1)
    b.add_argument('--workers',type=int,choices=[1,2,3,4],default=2)
    b.add_argument('--seconds',type=int,default=900);b.add_argument('--max-calls',type=int,default=45)
    b.add_argument('--freeze',type=Path)
    o=sub.add_parser('compose');o.add_argument('--topic-file',type=Path,required=True)
    o.add_argument('--sources-file',type=Path,default=DATA/'sources.json');o.add_argument('--out',type=Path,required=True)
    o.add_argument('--generations',type=int,default=2)
    r=sub.add_parser('report');r.add_argument('--out',type=Path,required=True)
    f=sub.add_parser('freeze');f.add_argument('--pilot',type=Path,required=True);f.add_argument('--out',type=Path,required=True)
    args=p.parse_args();load_env(args.env_file)
    if args.command=='benchmark':benchmark(args)
    elif args.command=='compose':
        topic=json.loads(args.topic_file.read_text(encoding='utf-8-sig'))
        all_sources=json.loads(args.sources_file.read_text(encoding='utf-8-sig'))
        cards={k:all_sources[k] for k in topic.get('source_ids',[])}
        result=ClassicalEvolution(topic,cards,DeepSeekClient(model=args.model),args.out,
            config={'generations':args.generations},progress=lambda s:print(s,flush=True)).run()
        print(dumps({'status':result['status'],'poem':result['poem'],'budget':result['budget']}))
    elif args.command=='report':print(dumps(summarize(args.out)))
    else:
        status=summarize(args.pilot)
        if not status['all_terminal']:raise ValueError('pilot has unfinished jobs')
        pb=json.loads((args.pilot/'experiment-binding.json').read_text(encoding='utf-8'))
        if pb['code_sha256']!=code_digest():
            raise ValueError('implementation changed after pilot; rerun pilot before freezing')
        topics,sources=load_data()
        freeze={'protocol':VERSION,'code_sha256':code_digest(),'sources_sha256':digest(sources),
            'held_out_sha256':digest([t for t in topics if t['split']=='held_out']),
            'pilot_binding_sha256':digest(pb),'config':pb['config'],'model':pb['model'],
            'pilot_completed':status,'note':'frozen before held-out API calls; failures stay in denominator'}
        if args.out.exists():raise ValueError('freeze already exists')
        atomic_write(args.out,freeze);print('Frozen:',args.out)


if __name__=='__main__':main()
