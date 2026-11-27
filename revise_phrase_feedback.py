import json
from dataclasses import asdict
from pathlib import Path
from experiments.classical_expression.run import ROOT,Transport,Adapter,save
from experiments.classical_expression.poetics_v2 import WRITER_SYSTEM,audit
from experiments.reverse_prompt_engineering.llm import Budget,LLM,LLMCache,JsonlLedger,restore_budget_from_ledger
from poetry_agent.client import DeepSeekClient,load_env
from poetry_agent.core import Poem,Task,check,_metrical_target_and_report
from poetry_agent.aesthetics import compare_bidirectional
root=ROOT/'allusion-study-01';r=root/'runs/compression-01';dest=r/'01-user-feedback-revision.json'
if dest.exists():raise SystemExit('existing feedback revision preserved')
feedback={'user_quote':'眼卷开可以理解，一吃下咽也可以理解，但是失步行太生硬了','normalized_referents':['眼倦开','一匙下咽','失步行'],'preference':'前两处可以理解；失步行太生硬','not_a_claim':'不将可以理解升级为最佳表达，也不从这次认可推断所有陌生搭配都成立'}
save(root/'feedback-phrase-naturalness.json',feedback)
load_env(ROOT.parents[2]/'poetry-agent/.env');b=Budget(12,50000);restore_budget_from_ledger(b,r/'ledger.jsonl')
l=LLM(Transport(DeepSeekClient()),b,LLMCache(r/'cache.jsonl'),JsonlLedger(r/'ledger.jsonl'),max_parse_retries=0)
old=json.loads((r/'01.json').read_text(encoding='utf8'));prompt=old['prompt'];cards=[c for c in json.loads((root/'cards.json').read_text(encoding='utf8'))['cards'] if c['id']=='ye-wei']
payload={'prompt':prompt,'draft':old['revision'],'source_cards':cards,'feedback':'失步行太生硬，不要再用近义拼合的词替它。重点改第二句，尽量保留其余有效处。第二句可写这份安排的具体拘束、代价或所失，给第三句用典留下承担选择的空间，不再重复说不愿随人。不是把全诗改成白话；七绝，允许必要整句重写，换韵须通篇一致。'}
d,meta=l.call_json(purpose='phrase_feedback_revision',system=WRITER_SYSTEM,user=json.dumps(payload,ensure_ascii=False),max_tokens=4096,thinking='disabled')
poem=asdict(Poem.parse(json.dumps(d,ensure_ascii=False)));task=Task(prompt,'qijue',4,qijue_pattern='ping_rhyme')
row={'original':old['revision'],'revision':poem,'hard_issues':check(Poem(**poem),task),'meter':_metrical_target_and_report(poem,task)[1],'user_feedback':feedback,'meta':meta}
save(r/'01-user-feedback-checkpoint.json',row)
row['audit']=audit(prompt,poem,cards,l)
row['comparison']=compare_bidirectional(old['revision'],poem,{'topic':prompt,'genre':'qijue','max_lines':4},Adapter(l,'phrase-feedback'),120,relation='revision')
row['budget']=b.summary();row['quality_verified']=False;save(dest,row)
print(json.dumps({'poem':poem,'hard_issues':row['hard_issues'],'meter':row['meter']['status'],'audit':row['audit']['data'],'comparison_status':row['comparison']['selection_status'],'choice':row['comparison']['assessment']['choice'],'calls':b.calls},ensure_ascii=False))
