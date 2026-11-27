"""Post-run symmetric blind comparison. Does not change generation or selection."""
import argparse,concurrent.futures,json,sys
from pathlib import Path
from poetry_agent.client import DeepSeekClient,load_env
from poetry_agent.aesthetics import compare_bidirectional
from poetry_agent.style.corpus import write as atomic_write
from experiments.classical_evolution.store import RunStore,RecordedClient,digest

def main():
 sys.stdout.reconfigure(encoding='utf-8')
 p=argparse.ArgumentParser();p.add_argument('--directory',type=Path,required=True);p.add_argument('--workers',type=int,choices=[1,2,3,4],default=4);args=p.parse_args()
 root=Path(__file__).resolve().parent;load_env(root.parent/'poetry-agent'/'.env')
 directory=args.directory;b=json.loads((directory/'experiment-binding.json').read_text(encoding='utf-8'))
 baseline_arm=next(arm for arm in b['arms'] if arm!='classical_evolution')
 pairs=sorted({(j['topic_id'],j['repetition']) for j in b['jobs']})
 def go(pair):
  tid,rep=pair;name=f'{tid}-r{rep}';topic=next(t for t in b['topics'] if t['id']==tid)
  results={}
  for arm in b['arms']:
   job=next(j for j in b['jobs'] if j['topic_id']==tid and j['repetition']==rep and j['arm']==arm)
   folder=Path(job.get('result_directory') or directory/'jobs'/job['key'])
   results[arm]=json.loads((folder/'result.json').read_text(encoding='utf-8'))
  binding={'protocol':'classical-symmetric-blind-0.1','experiment':b['experiment_sha256'],
    'input_results':digest(results),'model':b['model'],'original_prompt':topic['prompt']}
  store=RunStore(directory/'paired-blind'/name,binding)
  old=store.load('result.json')
  if old:return old
  a=results[baseline_arm];z=results['classical_evolution'];ap=a.get('poem');zp=z.get('poem')
  form='tie' if bool(ap)==bool(zp) else baseline_arm if ap else 'classical_evolution'
  api=RecordedClient(DeepSeekClient(model=b['model']),store,max_calls=4,seconds=180)
  row={'pair':name,'eligibility_winner':form,'literary_winner':None,
       'literary_quality_verified':False,'comparison_scope':'two eligible outputs only, symmetric AB/BA, model preference'}
  if ap and zp:
   try:
    comparison=compare_bidirectional(ap,zp,{'topic':topic['prompt'],'genre':topic['task']['genre']},api,120,relation='independent')
    choice=comparison['assessment']['choice'];row['comparison']=comparison
    row['literary_winner']={'a':baseline_arm,'b':'classical_evolution','tie':'tie'}[choice]
   except (RuntimeError,ValueError,KeyError,TypeError):row['comparison_status']='incomplete'
  else:row['comparison_status']='not_both_eligible'
  row['budget']=api.summary();store.save('result.json',row);print(name,row['eligibility_winner'],row['literary_winner'],flush=True);return row
 with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:rows=list(pool.map(go,pairs))
 report={'pairs':rows,'literary_wins':{arm:sum(r['literary_winner']==arm for r in rows) for arm in [*b['arms'],'tie']},
   'eligibility_wins':{arm:sum(r['eligibility_winner']==arm for r in rows) for arm in [*b['arms'],'tie']},
   'not_comparable':sum(r['literary_winner'] is None for r in rows),
   'calls':sum(r['budget']['calls'] for r in rows),'tokens':sum(r['budget']['tokens'] for r in rows),
   'warning':'Judges are models; AB/BA agreement is not human validation and sample size is small.'}
 atomic_write(directory/'paired-blind-summary.json',report);print(json.dumps({k:v for k,v in report.items() if k!='pairs'},ensure_ascii=False))
if __name__=='__main__':main()
