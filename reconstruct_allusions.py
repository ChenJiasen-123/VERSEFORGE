import json
from dataclasses import asdict
from experiments.classical_expression.run import ROOT,Transport,save
from experiments.classical_expression.allusion_trial import TOPICS,SYSTEM
from experiments.classical_expression.allusion_audit import audit
from experiments.classical_expression.protocol import review
from experiments.reverse_prompt_engineering.llm import Budget,LLM,LLMCache,JsonlLedger,restore_budget_from_ledger
from poetry_agent.client import DeepSeekClient,load_env
from poetry_agent.core import Task,Poem,check,_metrical_target_and_report,metrical_revision_feedback
from poetry_agent.qijue_profiles import specification
r=ROOT/'allusion-study-01/runs/paired-01';out=r/'reconstructed';out.mkdir(exist_ok=True)
cards=json.loads((ROOT/'allusion-study-01/cards.json').read_text(encoding='utf8'))['cards']
load_env(ROOT.parents[2]/'poetry-agent/.env');b=Budget(80,300000);restore_budget_from_ledger(b,r/'ledger.jsonl')
l=LLM(Transport(DeepSeekClient()),b,LLMCache(r/'cache.jsonl'),JsonlLedger(r/'ledger.jsonl'),max_parse_retries=1)
notes={'01':'不要将拒绝写成无代价的田园闲适；具体想保住什么、放弃什么？只围绕自主选择，不另加远水救急。','02':'原故事不能直接改写为四句；创造一个具体人间处境（不必现代），让眼前小助与将来大诺发生。拒绝救急的后果或判断应在正文成立。','03':'器物为何帮助人成长？为何不再适用？完成一次计算或写完一本书都不能证明此后不再需要。可选择能清楚呈现人成长后尺寸、用途变化的器物。不要仅有怀旧或用典说明。'}
for ident,prompt in TOPICS:
 p=out/(ident+'.json')
 if p.exists():continue
 print('PLAN '+ident,flush=True)
 plan,meta=l.call_json(purpose='allusion_reconstruct_plan',system='你是古典诗策划。先形成可实际经历的处境与表达，再决定怎样用典。不要写诗句。只返回JSON：{"scene":"谁在什么处境","experience":"想让读者经历的感情或思考","causal_basis":"题目要求如何实际成立","card_id":"给定ID或空串","meaning_added":"典故增加了什么，不止古雅","direction":"顺用或翻用，并说明区别","progression":"四句如何推进"}。不把典源故事移植为发生过的史实。',user=json.dumps({'prompt':prompt,'editorial_notes':notes[ident],'source_cards':cards},ensure_ascii=False),max_tokens=1800,thinking='disabled',cache_variant=ident)
 save(out/(ident+'-plan.json'),{'data':plan,'meta':meta})
 task=Task(prompt,'qijue',4,qijue_pattern='ping_rhyme');drafts=[]
 for n in range(2):
  payload={'prompt':prompt,'plan':plan,'source_cards':cards,'editorial_notes':notes[ident],'metrical_target':specification('ping_rhyme'),'instruction':'不是复述典源故事；让典源与本诗形成能读出的对应、反拨或价值判断。不限白描，允许直抒、反问、议论。只选与表达有作用的典，不强制堆叠。'}
  if drafts:payload['revision']={'draft':drafts[-1]['poem'],'audit':drafts[-1]['audit']['data'],'reading':drafts[-1]['blind']['data'],'meter_feedback':metrical_revision_feedback(drafts[-1]['poem'],task)}
  data,meta=l.call_json(purpose='allusion_reconstructed_poem',system=SYSTEM,user=json.dumps(payload,ensure_ascii=False),max_tokens=4096,thinking='disabled',cache_variant=f'{ident}-{n}')
  poem=asdict(Poem.parse(json.dumps(data,ensure_ascii=False)))
  row={'poem':poem,'claim':data.get('allusion'),'hard_issues':check(Poem(**poem),task),'meter':_metrical_target_and_report(poem,task)[1],'blind':review(prompt,poem,l),'audit':audit(prompt,poem,cards,l),'response_meta':meta}
  drafts.append(row);save(out/(ident+'-checkpoint.json'),{'plan':plan,'drafts':drafts})
  if not row['hard_issues'] and row['audit']['data']['decision']=='keep':break
 selected=min(drafts,key=lambda x:(len(x['hard_issues']),x['audit']['data']['decision']!='keep',x['blind']['data']['decision']!='keep'))
 save(p,{'prompt':prompt,'plan':plan,'drafts':drafts,'selected':selected,'quality_verified':False})
save(out/'summary.json',{'status':'reconstructed_three_pending_final_analysis','budget':b.summary()})
