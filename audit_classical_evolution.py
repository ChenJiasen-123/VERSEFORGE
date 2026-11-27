"""Recompute mechanical consistency from actual saved poems, not report flags."""
import argparse,json,sys
from pathlib import Path
from experiments.classical_evolution.engine import make_task,known_checks,gates
from experiments.classical_evolution.protocol import validate_reviews
from poetry_agent.style.corpus import write as atomic_write

def audit(directory):
 b=json.loads((directory/'experiment-binding.json').read_text(encoding='utf-8'));violations=[];rows=[]
 for j in b['jobs']:
  job=Path(j.get('result_directory') or directory/'jobs'/j['key']);p=job/'result.json'
  if not p.exists():violations.append({'job':j['key'],'issue':'missing terminal result'});continue
  r=json.loads(p.read_text(encoding='utf-8'));binding=json.loads((job/'binding.json').read_text(encoding='utf-8'))
  topic=next(t for t in b['topics'] if t['id']==j['topic_id']);task=make_task(topic)
  if binding['code_sha256']!=b['code_sha256']:violations.append({'job':j['key'],'issue':'mixed implementation versions'})
  ledger=json.loads((job/'call-ledger.json').read_text(encoding='utf-8'))
  if len(ledger)!=r['budget']['calls'] or len(ledger)>b['config']['max_calls']:
   violations.append({'job':j['key'],'issue':'call budget/count mismatch'})
  c=r.get('selected');mechanical=None
  if c:
   mechanical=known_checks(c['poem'],task)
   if mechanical['hard_issues']:violations.append({'job':j['key'],'issue':'selected poem has known hard failures','details':mechanical['hard_issues']})
   if r['poem']!=c['poem']:violations.append({'job':j['key'],'issue':'selected/output poem mismatch'})
   try:validate_reviews({'reviews':[c['review']]},[c],{f'r{i+1}':q for i,q in enumerate(topic['requirements'])},binding['sources'])
   except (ValueError,KeyError,TypeError):violations.append({'job':j['key'],'issue':'invalid selected review evidence'})
   if mechanical['meter']['status']=='unknown' and r['status']!='candidate_with_unresolved_readings':
    violations.append({'job':j['key'],'issue':'unknown reading not disclosed'})
  if j['arm']=='classical_evolution':
   state=json.loads((job/'state.json').read_text(encoding='utf-8'));archive={p['id']:p for p in state['archive']}
   if r.get('completed_generations')!=b['config']['generations']:
    violations.append({'job':j['key'],'issue':'requested evolution generations incomplete'})
   for p in archive.values():
    observed=known_checks(p['poem'],task)
    if observed['hard_issues']!=p['checks']['hard_issues'] or observed['meter']['status']!=p['checks']['meter']['status']:
     violations.append({'job':j['key'],'issue':'saved candidate checks disagree with recomputation','candidate':p['id']})
    for parent in p['parent_ids']:
     if parent not in archive or archive[parent]['generation']>=p['generation']:
      violations.append({'job':j['key'],'issue':'invalid lineage','candidate':p['id']})
   if c and (c['id'] not in archive or archive[c['id']]['poem']!=c['poem']):
    violations.append({'job':j['key'],'issue':'selected poem is not a recorded ancestor/offspring'})
  providers=set()
  for p in (job/'calls').glob('*.json'):
   obj=json.loads(p.read_text(encoding='utf-8'));provider=(obj.get('response') or {}).get('provider') or {}
   if provider.get('model'):providers.add(provider['model'])
  rows.append({'job':j['key'],'recomputed_hard_clear':mechanical is not None and not mechanical['hard_issues'],
    'meter_status':mechanical['meter']['status'] if mechanical else None,'provider_models':sorted(providers),
    'literary_quality_verified':False})
 result={'expected_runs':len(b['jobs']),'terminal_results':len(rows),'violations':violations,'rows':rows,
  'mechanical_consistency_verified':not violations,'scope':'Recomputed hard constraints, recorded review quotations, lineage, versions and call counts. Not literary quality or source interpretation certification.'}
 atomic_write(directory/'mechanical-audit.json',result);return result
if __name__=='__main__':
 sys.stdout.reconfigure(encoding='utf-8');p=argparse.ArgumentParser();p.add_argument('directory',type=Path);a=p.parse_args();r=audit(a.directory);print(json.dumps({k:v for k,v in r.items() if k!='rows'},ensure_ascii=False))
