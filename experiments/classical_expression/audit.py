"""Offline evidence inventory and anonymized reader packet; never calls an API."""
import argparse
import hashlib
import json
import random
from pathlib import Path
from .selection import formal

ROOT=Path(__file__).resolve().parent

def audit(folder):
    topics=json.loads((ROOT/'topics.json').read_text(encoding='utf8'))
    tests=[t for t in topics if t['split']=='held_out']
    missing=[];groups={g:[] for g in 'ABC'};packet=[];mapping=[]
    for topic in tests:
        available=[]
        for group in 'ABC':
            path=folder/(group+'-'+topic['id']+'.json')
            if not path.exists():missing.append(path.name);continue
            row=json.loads(path.read_text(encoding='utf8'))
            groups[group].append({'topic':topic['id'],**formal(row),
                'expression_proxy':row.get('expression_proxy'),
                'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
            available.append((group,row['workflow']['poem']))
        random.Random('classical-expression-blind-v1:'+topic['id']).shuffle(available)
        for index,(group,poem) in enumerate(available):
            label=f'{topic["id"]}-{index+1}'
            packet.append({'label':label,'topic':topic['prompt'],'genre':topic['genre'],
                'poem':poem,'questions':['实际经历了什么？请引用正文。','句子如何推进这种体验？','修辞是否承担作用？','整体偏好与理由（可弃权）。']})
            mapping.append({'label':label,'group':group})
    missing_generations=[g for g in range(4) if not (folder/f'generation-{g}.json').exists()]
    status={'groups':groups,'missing_held_out':missing,'missing_generations':missing_generations,
        'frozen_strategies_present':(folder/'frozen-strategies.json').exists(),
        'automated_evidence_complete':not missing and not missing_generations and (folder/'frozen-strategies.json').exists(),
        'literary_improvement_verified':False,'human_blind_review':'pending',
        'formal_acceptance':{g:len(rows)==6 and all(r['meter']=='pass' and r['hard_count']==0 and r['requirements_confirmed'] for r in rows) for g,rows in groups.items()}}
    return status,packet,mapping

def main():
    p=argparse.ArgumentParser();p.add_argument('run_id');args=p.parse_args()
    folder=ROOT/'runs'/args.run_id
    if not folder.is_dir():raise SystemExit('run不存在')
    status,packet,mapping=audit(folder)
    # Output outside the run's version binding and do not mutate raw evidence.
    out=ROOT/'reports'/args.run_id;out.mkdir(parents=True,exist_ok=True)
    for name,data in [('audit',status),('blind',packet),('mapping-private',mapping)]:
        (out/(name+'.json')).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({'complete':status['automated_evidence_complete'],'missing_held_out':len(status['missing_held_out']),
        'missing_generations':status['missing_generations']},ensure_ascii=False))

if __name__=='__main__':main()
