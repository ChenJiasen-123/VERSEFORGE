import json
import http.client
from poetry_agent.aesthetics import failure_code
from pathlib import Path
from experiments.classical_expression.run import ROOT,Transport,evaluate,save
from experiments.reverse_prompt_engineering.llm import Budget,LLM,LLMCache,JsonlLedger,restore_budget_from_ledger,BudgetExhausted
from poetry_agent.client import DeepSeekClient,load_env
r=ROOT/'runs/evolution-01';f=json.loads((r/'frozen-strategies.json').read_text(encoding='utf8'))
load_env(ROOT.parents[2]/'poetry-agent/.env');b=Budget(1800,8000000);restore_budget_from_ledger(b,r/'ledger.jsonl')
l=LLM(Transport(DeepSeekClient()),b,LLMCache(r/'cache.jsonl'),JsonlLedger(r/'ledger.jsonl'),max_parse_retries=1)
for g in 'ABC':
 for t in json.loads((ROOT/'topics.json').read_text(encoding='utf8')):
  if t['split']!='held_out':continue
  p=r/(g+'-'+t['id']+'.json')
  if p.exists():continue
  print('RESUME '+g+' '+t['id'],flush=True)
  try:evaluate(t,f[g],l,p)
  except BudgetExhausted:raise
  except (ValueError,RuntimeError,KeyError,TypeError,OSError,http.client.HTTPException) as exc:
   save(r/(g+'-'+t['id']+'-failure.json'),{'failure_type':type(exc).__name__,'failure_code':failure_code(exc),'status':'failed_not_a_poem','schema_retries':1})
   print('FAILED '+g+' '+t['id']+' '+type(exc).__name__,flush=True)
count=sum((r/(g+'-test-'+str(i).zfill(2)+'.json')).exists() for g in 'ABC' for i in range(1,7))
save(r/'summary.json',{'status':'completed_full' if count==18 else 'benchmark_incomplete','held_out_completed':count,'budget':b.summary(),'quality_verified':False,'formal_acceptance_verified':False,'schema_repair_added_in_recovery':True})
