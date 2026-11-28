"""Raw-prompt validation: no hand-written task/profile/source IDs enter the creator."""
import argparse,concurrent.futures,hashlib,json,sys
from pathlib import Path
from poetry_agent.client import DeepSeekClient,load_env
from poetry_agent.style.corpus import write as atomic_write
from experiments.classical_evolution.run import load_data
from experiments.classical_evolution.engine import DEFAULT_CONFIG
from experiments.classical_evolution.store import digest,code_digest
import classical_agent
ROOT=Path(__file__).resolve().parent

def main():
 sys.stdout.reconfigure(encoding='utf-8');p=argparse.ArgumentParser();p.add_argument('--split',choices=['pilot','held_out'],required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--repetitions',type=int,choices=[1,2],default=1);p.add_argument('--workers',type=int,choices=[1,2,3,4],default=4);p.add_argument('--prepare-only',action='store_true');a=p.parse_args()
 topics,library=load_data();topics=[t for t in topics if t['split']==a.split]
 jobs=[{'key':f"{t['id']}-r{rep}-raw_classical_evolution",'topic_id':t['id'],'repetition':rep,'arm':'raw_classical_evolution'} for rep in range(1,a.repetitions+1) for t in topics]
 knowledge=json.loads((ROOT/'experiments/classical_expression/knowledge.json').read_text(encoding='utf-8'))
 binding={'protocol':classical_agent.VERSION,'role':'raw-prompt end-to-end study','split':a.split,'topics':topics,'sources':library,
  'arms':['raw_classical_evolution'],'jobs':jobs,'model':'deepseek-reasoner','config':DEFAULT_CONFIG,
  'code_sha256':code_digest(),'entry_source_sha256':hashlib.sha256((ROOT/'classical_agent.py').read_bytes()).hexdigest(),
  'driver_source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'poetics_sha256':digest(knowledge),
  'creation_inputs':'raw prompt + auto genre preference + full verified source library only; task/profile/source IDs selected automatically',
  'expected_task_fields':'topic.task and topic.requirements retained as evaluation metadata, never passed into run_raw',
  'limits':'Not a causal isolation of genetic operators; evaluates the complete raw-prompt route including automatic source selection and restored poetics.'}
 binding['experiment_sha256']=digest(binding)
 a.out.mkdir(parents=True,exist_ok=True);file=a.out/'experiment-binding.json'
 if file.exists():
  if json.loads(file.read_text(encoding='utf-8'))!=binding:raise ValueError('raw study binding changed; new directory required')
 else:
  if any(a.out.iterdir()):raise ValueError('nonempty unbound raw study')
  atomic_write(file,binding)
 if a.prepare_only:print('registered_raw_runs',len(jobs));return
 load_env(ROOT.parent/'poetry-agent'/'.env')
 def execute(j):
  out=a.out/'jobs'/j['key']
  if (out/'result.json').exists():return
  t=next(t for t in topics if t['id']==j['topic_id'])
  progress=lambda s:print(j['key'],s,flush=True)
  result=classical_agent.run_raw(t['prompt'],out,DeepSeekClient(model=binding['model']),hint='auto',library=library,
    config=DEFAULT_CONFIG,progress=progress)
  progress('terminal-'+result['status'])
 errors=[]
 with concurrent.futures.ThreadPoolExecutor(max_workers=a.workers) as pool:
  fs={pool.submit(execute,j):j for j in jobs}
  for f in concurrent.futures.as_completed(fs):
   try:f.result()
   except Exception as exc:errors.append({'job':fs[f]['key'],'error_type':type(exc).__name__})
 if errors:atomic_write(a.out/'driver-failures.json',errors)
 print('terminal_raw_runs',len(list((a.out/'jobs').glob('*/result.json'))),'/',len(jobs))
if __name__=='__main__':main()
