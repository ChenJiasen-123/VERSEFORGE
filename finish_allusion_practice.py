import json,sys
from pathlib import Path
from poetry_agent.client import DeepSeekClient,load_env
from poetry_agent.recording_client import RecordingClient
from poetry_agent.runtime_budget import BudgetedClient
from poetry_agent.allusion_policy import WRITER,READER
from poetry_agent.core import Poem,Task,_metrical_target_and_report
sys.stdout.reconfigure(encoding='utf-8')
root=Path(__file__).resolve().parent;load_env(root/'.env')
out=root/'research/allusion-practice-20261127T042751Z'
client=BudgetedClient(RecordingClient(DeepSeekClient(),out/'responses-followup.json'),180,3)
cases=[json.loads((out/f'{i:02d}.json').read_text(encoding='utf-8')) for i in range(1,4)]
payload=[{'source_card':r['source_card'],'exercise':r['exercise'],'previous':r['initial'],'review':r['initial_review']} for r in cases]
instruction='''这三首用典练习需要重新打磨。第一首：涸辙已承载救急与远诺的错位，不要再用两句讲小水/大水的典故故事，把字留给今夜的处境。第二首：曳尾可承载选择，不用“我择…行”把态度逐字说满，生活代价不自动以清江美景收尾。第三首：必须有可辨的学步/故步/邯郸等语意联系；不把泛泛改口音叫作化用。不借贺知章“客从何处来”冒充邯郸典，母亲不必突然不认识自己的孩子；重点是人物想说旧称却先用了练熟的说法。读者需要的句法联系不能省掉，不用奇怪词组凑韵。不要求尖锐、微动作或反转。只返回JSON：{"poems":[{"title":"","lines":["","","",""],"pattern":"ping_rhyme或ping_no_rhyme或ze_rhyme或ze_no_rhyme"}]}，恰好三首，依次对应材料。每首四句各七字。'''
r=client.complete(WRITER+instruction,json.dumps(payload,ensure_ascii=False),timeout=90,max_tokens=5000,thinking='disabled')
final=json.loads(r['content']);assert len(final['poems'])==3
for i,p in enumerate(final['poems']):
 poem=Poem.parse(json.dumps(p,ensure_ascii=False));task=Task(cases[i]['exercise'],'qijue',4,qijue_pattern=p['pattern'])
 p['meter']=_metrical_target_and_report({'title':poem.title,'lines':poem.lines},task)[1]
(out/'second-revisions.json').write_text(json.dumps(final,ensure_ascii=False,indent=2),encoding='utf-8')
review=client.complete(READER+'''核对每首与其源卡的关系。只返回JSON：{"reviews":[{"index":1,"decision":"keep或revise","allusion_anchor":"正文原文或空串","problem":"最强具体质疑","redundancy":"哪些字句重复交代，无则说明","keep_reason":"keep须回应质疑"}]}。不得替作者补造关系；少字不自动好，判断不须另加动作证明；不要照搬典源故事去替代当下处境。''',json.dumps([{'poem':{'title':p['title'],'lines':p['lines']},'source_card':cases[i]['source_card'],'exercise':cases[i]['exercise']} for i,p in enumerate(final['poems'])],ensure_ascii=False),timeout=90,max_tokens=4096,thinking='disabled')
(out/'second-revisions-review.json').write_text(review['content'],encoding='utf-8')
print(json.dumps({'poems':final['poems'],'reviews':json.loads(review['content']),'budget':client.summary()},ensure_ascii=False))
