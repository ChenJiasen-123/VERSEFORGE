import json,sys
from pathlib import Path
from datetime import datetime,timezone
from poetry_agent.client import DeepSeekClient,load_env
from poetry_agent.recording_client import RecordingClient
from poetry_agent.runtime_budget import BudgetedClient
from poetry_agent.allusion_policy import WRITER,READER
sys.stdout.reconfigure(encoding='utf-8');root=Path(__file__).resolve().parent;load_env(root/'.env')
out=root/'research'/('war-widow-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'));out.mkdir(parents=True)
client=BudgetedClient(RecordingClient(DeepSeekClient(),out/'responses.json'),180,4)
original='远方的亲人思念战死在沙场的丈夫'
sources=[{'name':'陈陶《陇西行》','source':'https://zh.wikisource.org/wiki/隴西行_(陳陶)','relation':'战地死亡与闺中思念并置；不要套写白骨对梦里人的现成结尾。'}, {'name':'王建《望夫石》','source':'https://zh.wikisource.org/wiki/望夫石_(王建)','text':'望夫处，江悠悠。化为石，不回头。山头日日风复雨，行人归来石应语。','relation':'凝固的等待与被唤醒说话的可能；可借其关系，但不要简单复述望夫化石。'}]
def ask(system,data,tokens=4096):return json.loads(client.complete(system,json.dumps(data,ensure_ascii=False),timeout=80,max_tokens=tokens,thinking='disabled')['content'])
def save(name,data):(out/name).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
writer=WRITER+'''本轮用户出题，写古典诗。先找到一种具体的思念体验，再用典故压缩背景。写两个不同构思的七言四句候选，各四句每句七字；人物是远在战场之外的妻子，丈夫已战死。她是否知死可自行选择，但全篇自洽，不假设必须不知死。必须有可辨认的用典语意联系，但不强制用给定材料；若不用给定材料，须写准确的典源供核对。不套陈陶原诗、不复制名句。不为催泪生造丧子、失忆、母不识儿等背景，不强制反转。只返回JSON：{"candidates":[{"title":"","lines":["","","",""],"source_used":"","expression":"核心体验","allusion_load":"典故承担什么"}]}。'''
drafts=ask(writer,{'user_prompt':original,'source_material':sources});save('drafts.json',drafts)
public=[{'title':p['title'],'lines':p['lines']} for p in drafts['candidates']]
review=ask(READER+'''独立审读两首。只返回JSON：{"selected_index":0,"reason":"为什么选这一首，允许指出两首都弱","reviews":[{"index":0,"quote":"原文","allusion_anchor":"原文或空","problem":"最重要问题","suggestion":"一项修改方向"}]}。不要看作者意图去补剧情，也不能把未写完整背景一律当缺陷。''',{'user_prompt':original,'poems':public,'source_material':sources},3072);save('review.json',review)
index=review['selected_index'];assert type(index) is int and 0<=index<len(public)
final=ask(writer+'''现在只修订所给这一首，不返回候选数组。只返回JSON：{"title":"","lines":["","","",""],"source_used":""}。严格四句各七字。保护表达中心，修复牵强词组，典故已经承担的内容不重复讲解。''',{'user_prompt':original,'draft':public[index],'review':review['reviews'][index],'source_material':sources},3072);save('revision.json',final)
shape=len(final['lines'])==4 and all(len(''.join(c for c in line if '\u4e00'<=c<='\u9fff'))==7 for line in final['lines'])
save('audit.json',{'shape_passed':shape,'quality_verified':False,'meter_certified':False,'budget':client.summary()})
print(json.dumps({'final':final,'shape_passed':shape,'budget':client.summary()},ensure_ascii=False))
print(out)
