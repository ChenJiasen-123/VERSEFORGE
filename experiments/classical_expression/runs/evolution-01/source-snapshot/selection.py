"""Explicit ordinal search policy, not a calibrated literary score."""
import hashlib
import json

def fingerprint(files):
    return hashlib.sha256(b''.join(str(p.name).encode()+b'\0'+p.read_bytes() for p in files)).hexdigest()

def bind_run(path,binding):
    if path.exists():
        if json.loads(path.read_text(encoding='utf8'))!=binding:
            raise ValueError('运行绑定已变化，请使用新的run-id；禁止混用结果')
    else:
        if any(path.parent.glob('*.jsonl')):raise ValueError('旧记录缺少版本绑定，禁止接续')
        path.write_text(json.dumps(binding,ensure_ascii=False,indent=2),encoding='utf8')

def formal(row):
    checks=row['workflow']['checks']
    if 'meter' in checks:
        meter=checks['meter'][1]['status'];hard=checks['hard'];req=checks['requirements']
    else:
        meter=(checks.get('final_meter') or {}).get('report',{}).get('status','unknown')
        hard=checks.get('final_hard_issues',[]);req=checks.get('final_requirement_report',{})
    return {'meter':meter,'hard_count':len(hard),'requirement_violations':len(req.get('violations',[])),
        'requirements_confirmed':bool(req.get('confirmed'))}

def rank(row):
    f=formal(row);b=row['blind']['data']
    # Requirements and formal evidence precede the model's literary preference.
    return (f['hard_count']+f['requirement_violations'],not f['requirements_confirmed'],
            {'pass':0,'unknown':1,'failed':2}[f['meter']],
            b['decision']!='keep',bool(b['gap'].strip()),len(b['device_risks']))

def population_rank(candidate):
    ranks=[e['rank'] for e in candidate['evidence']]
    return tuple(sum(r[i] for r in ranks) for i in range(6))
