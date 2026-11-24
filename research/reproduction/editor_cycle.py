import json
from pathlib import Path
from poetry_agent.client import load_env,DeepSeekClient
from poetry_agent.aesthetics import review,compare_bidirectional,failure_code
from poetry_agent.requirement_checks import safe_review
from poetry_agent.core import SYSTEM,MODERN_AESTHETIC,Poem

load_env('.env');client=DeepSeekClient()
out=Path('research/editor-cycle-01');out.mkdir(parents=True,exist_ok=True)
for name in ('returned-letter','supported-time-crossing'):
    prior=json.loads(Path(f'research/editor-probe-02/{name}.json').read_text(encoding='utf-8'))
    poem,task=prior['poem'],prior['task']
    record={'case':name,'task':task,'original':poem,'model':client.model,'responses':[]}
    def save(): (out/f'{name}.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    class Recorder:
        def complete(self,system,user,**kwargs):
            response=client.complete(system,user,**kwargs)
            record['responses'].append({'system':system,'user':json.loads(user),'response':response});save()
            return response
    c=Recorder()
    try:
        record['review']=review(poem,task,c,60);save()
        if record['review']['assessment']['decision']=='revise':
            payload={'task':task,'revision':{'draft':poem,'editor':record['review']['assessment'],
                'instruction':'只处理最重要的问题，保护成立的语言关系。实际寄语如有缺失必须补足，不能只声称存在。不要把诗改成解释。'}}
            response=c.complete(SYSTEM+MODERN_AESTHETIC,json.dumps(payload,ensure_ascii=False),timeout=90,max_tokens=8192,thinking='disabled')
            p=Poem.parse(response['content']); revised={'title':p.title,'lines':p.lines};record['revision']=revised;save()
            requirements=['不超过30行','包含写给十年后自己的一句话','包含系统提示片段','两者不得互相解释']
            record['requirements']=safe_review(task['topic'],revised,requirements,c);save()
            record['revision_review']=review(revised,task,c,60);save()
            record['comparison']=compare_bidirectional(poem,revised,task,c,60,relation='revision')
            record['adopt_revision']=(record['requirements']['confirmed'] and record['revision_review']['assessment']['decision']=='keep'
                and record['comparison']['selection_status']=='consensus' and record['comparison']['assessment']['choice']=='b')
        else: record['adopt_revision']=False
    except (ValueError,RuntimeError,KeyError,TypeError) as exc:
        record['failure_code']=failure_code(exc);record['adopt_revision']=False
    save();print(name,record.get('failure_code') or record['review']['assessment']['decision'],'adopt',record['adopt_revision'],flush=True)
