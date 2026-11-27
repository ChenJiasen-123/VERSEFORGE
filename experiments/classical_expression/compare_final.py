"""Post-freeze bidirectional comparisons. Refuses incomplete experiments."""
import argparse
import json
from pathlib import Path
from poetry_agent.aesthetics import compare_bidirectional
from poetry_agent.client import DeepSeekClient,load_env
from experiments.reverse_prompt_engineering.llm import Budget,LLM,LLMCache,JsonlLedger,restore_budget_from_ledger
from .audit import audit,ROOT
from .run import Adapter,Transport,save

def ready(folder):
    summary=folder/'summary.json'
    if not summary.exists() or json.loads(summary.read_text(encoding='utf8')).get('status')!='completed_full':
        raise ValueError('正式演化尚未结束，拒绝开启留出比较')
    status,_,_=audit(folder)
    if not status['automated_evidence_complete']:raise ValueError('演化或18首对照证据缺失')

def main():
    p=argparse.ArgumentParser();p.add_argument('run_id');p.add_argument('--live',action='store_true');args=p.parse_args()
    folder=ROOT/'runs'/args.run_id;ready(folder)
    if not args.live:
        print('18对正反序比较，正常36次调用；共享原实验1800次/800万token上限，不自动扩额。');return
    load_env(ROOT.parents[1]/'.env');load_env(ROOT.parents[2]/'poetry-agent'/'.env')
    budget=Budget(1800,8000000)
    restore_budget_from_ledger(budget,folder/'ledger.jsonl')
    restore_budget_from_ledger(budget,folder/'comparison-ledger.jsonl')
    llm=LLM(Transport(DeepSeekClient()),budget,LLMCache(folder/'comparison-cache.jsonl'),
        JsonlLedger(folder/'comparison-ledger.jsonl'),max_parse_retries=0)
    topics=[t for t in json.loads((ROOT/'topics.json').read_text(encoding='utf8')) if t['split']=='held_out']
    results=[]
    for topic in topics:
        for first,second in [('A','B'),('A','C'),('B','C')]:
            name=topic['id']+'-'+first+second;path=folder/(name+'-comparison.json')
            if path.exists():record=json.loads(path.read_text(encoding='utf8'))
            else:
                a=json.loads((folder/(first+'-'+topic['id']+'.json')).read_text(encoding='utf8'))['workflow']['poem']
                b=json.loads((folder/(second+'-'+topic['id']+'.json')).read_text(encoding='utf8'))['workflow']['poem']
                comparison=compare_bidirectional(a,b,{'topic':topic['prompt'],'genre':topic['genre'],'max_lines':4},
                    Adapter(llm,name),120,relation='independent')
                choice=comparison['assessment']['choice']
                record={'topic':topic['id'],'groups':[first,second],
                    'winner':({'a':first,'b':second}.get(choice) if comparison['selection_status']=='consensus' else None),
                    'comparison':comparison,'human_preference_verified':False}
                save(path,record)
            results.append(record)
    save(folder/'comparison-summary.json',{'results':results,'budget':budget.summary(),
        'C_wins_over_A':sum(r['groups']==['A','C'] and r['winner']=='C' for r in results),
        'same_model_family_judge':True,'human_preference_verified':False})

if __name__=='__main__':main()
