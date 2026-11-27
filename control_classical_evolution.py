"""Supplementary current-studio three-candidate control; frozen engine stays unchanged."""
import argparse,concurrent.futures,hashlib,json,sys
from pathlib import Path
from poetry_agent.client import DeepSeekClient,load_env
from poetry_agent.style.corpus import write as atomic_write
from experiments.classical_evolution import run as implementation
from experiments.classical_evolution.store import digest
from report_classical_evolution import report
ROOT=Path(__file__).resolve().parent
ORIGINAL_STUDIO=implementation.run_studio

def three_candidates(*a,**kw):
 kw['candidate_count']=3
 return ORIGINAL_STUDIO(*a,**kw)

def main():
 sys.stdout.reconfigure(encoding='utf-8');p=argparse.ArgumentParser();p.add_argument('--primary',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--prepare-only',action='store_true');p.add_argument('--workers',type=int,choices=[1,2,3,4],default=4);a=p.parse_args()
 primary=a.primary.resolve();b=json.loads((primary/'experiment-binding.json').read_text(encoding='utf-8'))
 source_hash=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
 jobs=[]
 for j in b['jobs']:
  if j['arm']=='classical_evolution':jobs.append({**j,'result_directory':str(primary/'jobs'/j['key'])})
  else:
   key=j['key'].replace('baseline_studio','multi_candidate_studio')
   jobs.append({**j,'key':key,'arm':'multi_candidate_studio'})
 binding={**b,'arms':['multi_candidate_studio','classical_evolution'],'jobs':jobs,
  'primary_experiment_sha256':b['experiment_sha256'],'control_source_sha256':source_hash,
  'intervention':'existing run_studio candidate_count=3; independent_editor=True and other existing behavior unchanged',
  'design_note':'Supplement registered after inspecting pilot outcomes and partial primary completion counts, before reading held-out poem packet. Retains original single-candidate comparison. Not a compute-matched ablation.'}
 binding['experiment_sha256']=digest({k:v for k,v in binding.items() if k!='experiment_sha256'})
 a.out.mkdir(parents=True,exist_ok=True);path=a.out/'experiment-binding.json'
 if path.exists():
  previous=json.loads(path.read_text(encoding='utf-8'))
  if previous!=binding:
   if not a.prepare_only or any((a.out/'jobs').rglob('*.json')):raise ValueError('supplement binding changed after calls')
   atomic_write(a.out/'registration-revisions'/f"{previous['experiment_sha256']}.json",previous)
   atomic_write(path,binding)
 else:
  if any(a.out.iterdir()):raise ValueError('nonempty unbound output directory')
  atomic_write(path,binding)
 if a.prepare_only:print('supplement_registered',len([j for j in jobs if j['arm']=='multi_candidate_studio']));return
 missing=[j['key'] for j in b['jobs'] if not (primary/'jobs'/j['key']/'result.json').exists()]
 if missing:raise ValueError('primary generation is still incomplete; wait for its existing process')
 implementation.run_studio=three_candidates
 load_env(ROOT.parent/'poetry-agent'/'.env')
 config={**b['config'],'studio_candidate_count':3,'supplement_source_sha256':source_hash}
 def execute(j):
  if j['arm']!='multi_candidate_studio':return
  directory=a.out/'jobs'/j['key']
  if (directory/'result.json').exists():return
  topic=next(t for t in b['topics'] if t['id']==j['topic_id']);sources={k:b['sources'][k] for k in topic['source_ids']}
  progress=lambda stage:print(j['key'],stage,flush=True)
  r=implementation.baseline(topic,sources,DeepSeekClient(model=b['model']),directory,config,progress)
  print(j['key'],'terminal-'+r['status'],flush=True)
 failures=[]
 with concurrent.futures.ThreadPoolExecutor(max_workers=a.workers) as pool:
  fs={pool.submit(execute,j):j for j in jobs if j['arm']=='multi_candidate_studio'}
  for f in concurrent.futures.as_completed(fs):
   try:f.result()
   except Exception as exc:failures.append({'job':fs[f]['key'],'error_type':type(exc).__name__})
 if failures:atomic_write(a.out/'driver-failures.json',failures)
 summary=report(a.out)
 print(json.dumps({'all_terminal':summary['complete'],'completed':summary['terminal_runs'],'expected':summary['expected_runs']}),flush=True)
if __name__=='__main__':main()
