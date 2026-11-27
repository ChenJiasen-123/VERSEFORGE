import json
from dataclasses import asdict
from experiments.classical_expression.run import ROOT,Transport,Adapter,save
from experiments.classical_expression.poetics_v2 import WRITER_SYSTEM,audit
from experiments.classical_expression.allusion_trial import TOPICS
from experiments.reverse_prompt_engineering.llm import Budget,LLM,LLMCache,JsonlLedger,restore_budget_from_ledger
from poetry_agent.client import DeepSeekClient,load_env
from poetry_agent.core import Poem,Task,check,_metrical_target_and_report
from poetry_agent.qijue_profiles import specification
from poetry_agent.aesthetics import compare_bidirectional
root=ROOT/'allusion-study-01';prior=root/'runs/paired-01';out=root/'runs/compression-01';out.mkdir(exist_ok=True)
load_env(ROOT.parents[2]/'poetry-agent/.env');budget=Budget(12,50000);restore_budget_from_ledger(budget,out/'ledger.jsonl')
l=LLM(Transport(DeepSeekClient()),budget,LLMCache(out/'cache.jsonl'),JsonlLedger(out/'ledger.jsonl'),max_parse_retries=0)
cards=json.loads((root/'cards.json').read_text(encoding='utf8'))['cards']
cases=[('01',prior/'reconstructed/01.json','ye-wei'),('02',prior/'focused-02/final-attempt.json','he-zhe')]
for ident,path,cid in cases:
 dest=out/(ident+'.json')
 if dest.exists():continue
 d=json.loads(path.read_text(encoding='utf8'));old=d.get('selected',d)['poem'];prompt=dict(TOPICS)[ident];card=[c for c in cards if c['id']==cid]
 payload={'prompt':prompt,'draft':old,'source_cards':card,'metrical_target':specification('ping_rhyme'),'editing_instruction':'典故不是加在解释上的装饰。先删去典故已经承担的背景、关系或态度的重复说明，把四句留给此刻独有的细节或新的判断。不是省字比赛，也不要把全部意思塞进生硬短语。保持七绝，允许直接表达；今夜一餐不可变成活一秋。只返回title、lines JSON。'}
 print('REVISE '+ident,flush=True)
 response,meta=l.call_json(purpose='allusion_compression_revision',system=WRITER_SYSTEM,user=json.dumps(payload,ensure_ascii=False),max_tokens=4096,thinking='disabled')
 poem=asdict(Poem.parse(json.dumps(response,ensure_ascii=False)));task=Task(prompt,'qijue',4,qijue_pattern='ping_rhyme')
 row={'prompt':prompt,'original':old,'revision':poem,'hard_issues':check(Poem(**poem),task),'meter':_metrical_target_and_report(poem,task)[1],'response_meta':meta}
 save(out/(ident+'-checkpoint.json'),row)
 row['independent_audit']=audit(prompt,poem,card,l)
 row['comparison']=compare_bidirectional(old,poem,{'topic':prompt,'genre':'qijue','max_lines':4},Adapter(l,'compression-'+ident),120,relation='revision')
 row['quality_verified']=False;save(dest,row)
save(out/'summary.json',{'status':'two_revisions_and_comparisons_completed','budget':budget.summary(),'quality_verified':False})
