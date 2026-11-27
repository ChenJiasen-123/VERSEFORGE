import json
from pathlib import Path
from dataclasses import asdict
from experiments.classical_expression.run import ROOT,Transport,save
from experiments.classical_expression.protocol import review
from experiments.classical_expression.allusion_trial import SYSTEM,TOPICS
from experiments.reverse_prompt_engineering.llm import Budget,LLM,LLMCache,JsonlLedger,restore_budget_from_ledger
from poetry_agent.client import DeepSeekClient,load_env
from poetry_agent.core import Task,Poem,check,_metrical_target_and_report,metrical_revision_feedback
from poetry_agent.requirement_checks import safe_review
from poetry_agent.qijue_profiles import specification
r=ROOT/'allusion-study-01/runs/paired-01';out=r/'refinements';out.mkdir(exist_ok=True)
load_env(ROOT.parents[2]/'poetry-agent/.env');budget=Budget(80,300000);restore_budget_from_ledger(budget,r/'ledger.jsonl')
l=LLM(Transport(DeepSeekClient()),budget,LLMCache(r/'cache.jsonl'),JsonlLedger(r/'ledger.jsonl'),max_parse_retries=1)
feedback={'01':'只保留与拒聘自主选择有关的一组典故，删除涸辙枝蔓；沿原义不是翻用。不可借典源假称召平主动辞职。让拒绝的代价或所守显出，不以闲适风景替代选择；读农禾语义不成立。','02':'不要把庄子原故事改写成四句，换到当下具体人物的救急处境，让典故使大小、远近、缓急的错位更清楚。避免断策、远引寒等空泛生硬搭配。允许反问与议论，但须回应处境。','03':'写完书不代表砚台不再适用，原稿因果不足。可更换器物，先建立它为何帮助成长、为何如今不适用。得鱼忘筌不等于忘恩负义；保留镇纸是改用，不能单凭作者解释称化用已成立。'}
for ident,prompt in TOPICS:
 p=out/(ident+'.json')
 if p.exists():continue
 old=json.loads((r/(ident+'-source_guided.json')).read_text(encoding='utf8'));task=Task(prompt,'qijue',4,qijue_pattern='ping_rhyme')
 prior=old['selected']['poem'];drafts=[]
 for n in range(2):
  print('REFINE '+ident+' '+str(n+1),flush=True)
  payload={'prompt':prompt,'draft':prior,'source_cards':json.loads((ROOT/'allusion-study-01/cards.json').read_text(encoding='utf8'))['cards'],'editorial_feedback':feedback[ident],'metrical_target':specification('ping_rhyme'),'meter_feedback':metrical_revision_feedback(prior,task),'instruction':'按具体问题改写，勿替字凑谱造成病句。注意标题、禁词、七言四句和平水韵。'}
  d,meta=l.call_json(purpose='allusion_targeted_revision',system=SYSTEM,user=json.dumps(payload,ensure_ascii=False),max_tokens=4096,thinking='disabled',cache_variant=f'refine-{ident}-{n}')
  poem=asdict(Poem.parse(json.dumps(d,ensure_ascii=False)));blind=review(prompt,poem,l)
  row={'poem':poem,'allusion_claim':d.get('allusion'),'hard_issues':check(Poem(**poem),task),'meter':_metrical_target_and_report(poem,task)[1],'blind':blind,'meta':meta}
  drafts.append(row);save(out/(ident+'-checkpoint.json'),{'drafts':drafts})
  prior=poem
  if not row['hard_issues'] and row['blind']['data']['decision']=='keep':break
 selected=min(drafts,key=lambda x:(len(x['hard_issues']),x['blind']['data']['decision']!='keep'))
 save(p,{'original':old['selected'],'editorial_feedback':feedback[ident],'drafts':drafts,'selected':selected,'quality_verified':False,'allusion_accuracy_independently_verified':False})
save(out/'summary.json',{'status':'revised_three_pending_source_audit','budget':budget.summary()})
