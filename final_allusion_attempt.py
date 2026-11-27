import json
from dataclasses import asdict
from experiments.classical_expression.run import ROOT,Transport,save
from experiments.classical_expression.allusion_trial import SYSTEM,TOPICS
from experiments.classical_expression.allusion_audit import audit
from experiments.reverse_prompt_engineering.llm import Budget,LLM,LLMCache,JsonlLedger,restore_budget_from_ledger
from poetry_agent.client import DeepSeekClient,load_env
from poetry_agent.core import Task,Poem,check,_metrical_target_and_report,metrical_revision_feedback
from poetry_agent.qijue_profiles import specification
r=ROOT/'allusion-study-01/runs/paired-01';p=r/'focused-02/final-attempt.json'
if p.exists():raise SystemExit('already saved')
load_env(ROOT.parents[2]/'poetry-agent/.env');b=Budget(80,300000);restore_budget_from_ledger(b,r/'ledger.jsonl')
l=LLM(Transport(DeepSeekClient()),b,LLMCache(r/'cache.jsonl'),JsonlLedger(r/'ledger.jsonl'),max_parse_retries=0)
d=json.loads((r/'focused-02/result.json').read_text(encoding='utf8'));old=d['selected']['poem'];prompt=TOPICS[1][1];task=Task(prompt,'qijue',4,qijue_pattern='ping_rhyme')
card=[c for c in json.loads((ROOT/'allusion-study-01/cards.json').read_text(encoding='utf8'))['cards'] if c['id']=='he-zhe']
raw,meta=l.call_json(purpose='final_focused_allusion_revision',system=SYSTEM,user=json.dumps({'prompt':prompt,'draft':old,'source_cards':card,'metrical_target':specification('ping_rhyme'),'meter_feedback':metrical_revision_feedback(old,task),'instruction':'修正正文而非解释：急需的是今夜一餐，不是一秋或整季，禁止以度一秋或活一秋偷换任务。保留来春开义廪与今夜一餐的关系。典为顺用，不称翻用。第四句第三字之为平而指定位置须仄，修字须语句自然。四句各七字，第一二四句同平水韵，勿以生造词凑韵。允许改换韵字，但不可改变缓急冲突。'},ensure_ascii=False),max_tokens=4096,thinking='disabled')
poem=asdict(Poem.parse(json.dumps(raw,ensure_ascii=False)))
row={'poem':poem,'claim':raw.get('allusion'),'hard_issues':check(Poem(**poem),task),'meter':_metrical_target_and_report(poem,task)[1],'response_meta':meta}
save(r/'focused-02/final-attempt-checkpoint.json',row)
row['audit']=audit(prompt,poem,card,l);row['budget']=b.summary();row['quality_verified']=False
save(p,row)
print(json.dumps({'poem':poem,'issues':row['hard_issues'],'meter':row['meter']['status'],'audit':row['audit']['data'],'budget':row['budget']},ensure_ascii=False))
