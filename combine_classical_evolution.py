"""One blind packet of unique workflow runs across the primary and supplementary control."""
import argparse,json
from pathlib import Path
from poetry_agent.style.corpus import write as atomic_write
from experiments.classical_evolution.store import digest

def main():
 p=argparse.ArgumentParser();p.add_argument('--primary',type=Path,required=True);p.add_argument('--control',type=Path,required=True);p.add_argument('--raw',type=Path);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
 primary=a.primary.resolve();control=a.control.resolve()
 b=json.loads((primary/'experiment-binding.json').read_text(encoding='utf-8'));c=json.loads((control/'experiment-binding.json').read_text(encoding='utf-8'))
 if any(b[k]!=c[k] for k in ['topics','sources','model','code_sha256']):raise ValueError('studies differ in shared inputs')
 jobs=[{**j,'result_directory':str(primary/'jobs'/j['key'])} for j in b['jobs']]
 jobs += [{**j,'result_directory':str(control/'jobs'/j['key'])} for j in c['jobs'] if j['arm']=='multi_candidate_studio']
 if len({j['key'] for j in jobs})!=len(jobs):raise ValueError('duplicate workflow run')
 binding={**b,'arms':['baseline_studio','multi_candidate_studio','classical_evolution'],'jobs':jobs,
  'role':'three_arm_reading_union; references existing unique runs, no repeated generation',
  'linked_experiments':[b['experiment_sha256'],c['experiment_sha256']]}
 if a.raw:
  raw=a.raw.resolve();r=json.loads((raw/'experiment-binding.json').read_text(encoding='utf-8'))
  if any(b[k]!=r[k] for k in ['topics','sources','model','code_sha256']):raise ValueError('raw study differs in shared evaluation inputs')
  jobs += [{**j,'result_directory':str(raw/'jobs'/j['key'])} for j in r['jobs']]
  binding.update(arms=binding['arms']+['raw_classical_evolution'],jobs=jobs,
   role='four_arm_reading_union; raw route is a separate multi-change variant, not a genetic-operator ablation',
   entry_source_sha256=r['entry_source_sha256'],poetics_sha256=r['poetics_sha256'],linked_experiments=binding['linked_experiments']+[r['experiment_sha256']])
 binding['experiment_sha256']=digest({k:v for k,v in binding.items() if k!='experiment_sha256'})
 a.out.mkdir(parents=True,exist_ok=True);path=a.out/'experiment-binding.json'
 if path.exists() and json.loads(path.read_text(encoding='utf-8'))!=binding:raise ValueError('union binding changed')
 atomic_write(path,binding);print('unique_workflow_runs',len(jobs),'per_arm',len(jobs)//len(binding['arms']))
if __name__=='__main__':main()
