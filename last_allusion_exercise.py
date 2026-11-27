import json,sys
from pathlib import Path
from poetry_agent.client import DeepSeekClient,load_env
from poetry_agent.recording_client import RecordingClient
sys.stdout.reconfigure(encoding='utf-8');root=Path(__file__).resolve().parent;load_env(root/'.env')
out=root/'research/allusion-practice-20261127T042751Z'
client=RecordingClient(DeepSeekClient(),out/'responses-final-exercise.json')
system='''写一首七言四句的诗，题为《归家》。专项练习用典，不是翻译成语。第一二句中必须有“邯郸”二字，确实借学步失故步来承载“为融入异乡刻意改口、后来旧声难回”的经历，省掉这段经历的长篇交代。后两句转到归家当下：他想像小时候那样唤母亲，出口却是练熟的客语；母亲仍熟悉他的儿时称呼。让两种熟悉/陌生相撞，不安排母亲认不出亲儿，不把典故的结论再说一遍，不以抽象道理结尾。语言自然，避免“旧时名”“何处生”“先熟”等生硬或含混搭配。只返回JSON：{"title":"归家","lines":["","","",""]}。'''
r=client.complete(system,'请创作。',timeout=60,max_tokens=2048,thinking='disabled')
(out/'final-exercise.json').write_text(r['content'],encoding='utf-8');print(r['content'])
