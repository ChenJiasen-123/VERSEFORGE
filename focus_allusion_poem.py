import json
from dataclasses import asdict
from experiments.classical_expression.run import ROOT,Transport,save
from experiments.classical_expression.allusion_trial import SYSTEM,TOPICS
from experiments.classical_expression.allusion_audit import audit
from experiments.classical_expression.protocol import review
from experiments.reverse_prompt_engineering.llm import Budget,LLM,LLMCache,JsonlLedger,restore_budget_from_ledger
from poetry_agent.client import DeepSeekClient,load_env
from poetry_agent.core import Task,Poem,check,_metrical_target_and_report,metrical_revision_feedback
from poetry_agent.requirement_checks import safe_review
from poetry_agent.qijue_profiles import specification
r=ROOT/'allusion-study-01/runs/paired-01';out=r/'focused-02';out.mkdir(exist_ok=True)
load_env(ROOT.parents[2]/'poetry-agent/.env');b=Budget(80,300000);restore_budget_from_ledger(b,r/'ledger.jsonl')
l=LLM(Transport(DeepSeekClient()),b,LLMCache(r/'cache.jsonl'),JsonlLedger(r/'ledger.jsonl'),max_parse_retries=0)
cards=[c for c in json.loads((ROOT/'allusion-study-01/cards.json').read_text(encoding='utf8'))['cards'] if c['id']=='he-zhe']
prompt=TOPICS[1][1];task=Task(prompt,'qijue',4,qijue_pattern='ping_rhyme')
old=json.loads((r/'reconstructed/02.json').read_text(encoding='utf8'))['selected'];poem=old['poem'];drafts=[]
for n in range(2):
 print('FOCUS '+str(n+1),flush=True)
 payload={'prompt':prompt,'draft':poem,'source_cards':cards,'metrical_target':specification('ping_rhyme'),'meter_feedback':metrical_revision_feedback(poem,task),'editorial_feedback':'保留明春义仓与今夜求粥的缓急冲突，这是顺用原典，不是翻用。不需写鱼、西江等原故事物象；暗用须由错位关系而非词汇成立。别替人物编造慈善真心或恶意。腹空鸣较直，几钱只求语法可清理，寒粥向谁炉搭配不通。粥未得不能写成已经拿到冷粥。首句入韵，1/2/4句同平水韵；不要为韵制造病句。可以重写，不强制反问、沉默或身体触摸。'}
 if drafts:payload['independent_audit']=drafts[-1]['audit']['data']
 d,meta=l.call_json(purpose='focused_allusion_revision',system=SYSTEM,user=json.dumps(payload,ensure_ascii=False),max_tokens=4096,thinking='disabled',cache_variant=f'focus-{n}')
 poem=asdict(Poem.parse(json.dumps(d,ensure_ascii=False)))
 row={'poem':poem,'claim':d.get('allusion'),'hard_issues':check(Poem(**poem),task),'meter':_metrical_target_and_report(poem,task)[1],'audit':audit(prompt,poem,cards,l),'blind':review(prompt,poem,l)}
 drafts.append(row);save(out/'checkpoint.json',{'original':old,'drafts':drafts,'budget':b.summary()})
selected=min(drafts,key=lambda x:(len(x['hard_issues']),x['audit']['data']['decision']!='keep',x['blind']['data']['decision']!='keep'))
class Adapter:
 def complete(self,system,user,timeout=60,max_tokens=4096,thinking=None):
  content,meta=l.call_text(purpose='focused_requirements',system=system,user=user,max_tokens=max_tokens,thinking=thinking);return {'content':content,**meta}
requirements=safe_review(prompt,selected['poem'],[prompt],Adapter())
save(out/'result.json',{'original':old,'drafts':drafts,'selected':selected,'requirements':requirements,'budget':b.summary(),'quality_verified':False})
