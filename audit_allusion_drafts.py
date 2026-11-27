import json
from experiments.classical_expression.run import ROOT,Transport,save
from experiments.classical_expression.allusion_trial import TOPICS
from experiments.classical_expression.allusion_audit import audit
from experiments.reverse_prompt_engineering.llm import Budget,LLM,LLMCache,JsonlLedger,restore_budget_from_ledger
from poetry_agent.client import DeepSeekClient,load_env
r=ROOT/'allusion-study-01/runs/paired-01';out=r/'refinements';cards=json.loads((ROOT/'allusion-study-01/cards.json').read_text(encoding='utf8'))['cards']
load_env(ROOT.parents[2]/'poetry-agent/.env');b=Budget(80,300000);restore_budget_from_ledger(b,r/'ledger.jsonl')
l=LLM(Transport(DeepSeekClient()),b,LLMCache(r/'cache.jsonl'),JsonlLedger(r/'ledger.jsonl'),max_parse_retries=1)
for ident,prompt in TOPICS:
 p=out/(ident+'-independent-audit.json')
 if p.exists():continue
 d=json.loads((out/(ident+'.json')).read_text(encoding='utf8'))
 save(p,audit(prompt,d['selected']['poem'],cards,l));print('AUDITED '+ident,flush=True)
save(out/'audit-budget.json',b.summary())
