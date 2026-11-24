import json
from pathlib import Path
from poetry_agent.client import load_env,DeepSeekClient
from poetry_agent.aesthetics import compare_bidirectional

load_env('.env');c=DeepSeekClient();out=Path('research/sound-contrast-01');out.mkdir(exist_ok=True)
cases=[{'name':'borrowed-name','task':{'genre':'modern','topic':'写一首关于搬离旧居的现代诗，不超过12行；不要求克制或反转。'},
 'a':{'title':'搬家','lines':['最后一箱搬下去。','楼上有人喊我，','我答应了一声。','原来喊的是新来的邻居，','他和我同名。','同名，也好。','这楼里还有人可以答应。']},
 'b':{'title':'搬家','lines':['最后一箱搬下去。','楼上有人喊我，','我答应了一声。','原来喊的是新来的邻居，','他和我同名。','我感到名字不会离开这栋楼，','生活依然会继续。']}},
 {'name':'call-home','task':{'genre':'modern','topic':'写一首给家里打电话的现代诗，不超过12行；可以直说感情，不必用物象收尾。'},
 'a':{'title':'电话','lines':['妈说，吃了。','我说，吃了。','两口锅隔着八百里，','都还没有洗。','我们又说了一会儿，','谁也不先把水龙头打开。']},
 'b':{'title':'电话','lines':['妈说吃了，我也说吃了。','我们的两口锅隔着八百里，都还没有洗。','我们又说了一会儿，谁也不先把水龙头打开。']}}]
for case in cases:
    record=dict(case);record['source']='assistant-authored diagnostic contrasts, not human preference labels'
    record['comparison']=compare_bidirectional(case['a'],case['b'],case['task'],c,60)
    (out/(case['name']+'.json')).write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    print(case['name'],record['comparison']['selection_status'],record['comparison']['assessment']['choice'],flush=True)
