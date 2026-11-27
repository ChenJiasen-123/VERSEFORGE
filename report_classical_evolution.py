"""Descriptive benchmark report. Keeps model proxies separate from blind reading."""
import argparse,json,statistics,math,hashlib,random
from pathlib import Path
from poetry_agent.style.corpus import write as atomic_write

def report(directory):
 binding=json.loads((directory/'experiment-binding.json').read_text(encoding='utf-8'))
 jobs=binding['jobs'];rows=[];missing=[];blind=[];mapping=[]
 for j in jobs:
  p=Path(j.get('result_directory') or directory/'jobs'/j['key'])/'result.json'
  if not p.exists():missing.append(j['key']);continue
  r=json.loads(p.read_text(encoding='utf-8'));topic=next(t for t in binding['topics'] if t['id']==j['topic_id'])
  selected=r.get('selected');read=(selected or {}).get('review') or {};budget=r.get('budget') or {}
  readable=selected or r.get('best_unfinished')
  if readable:
   bid=hashlib.sha256((binding['experiment_sha256']+j['key']).encode()).hexdigest()[:12]
   blind.append({'id':bid,'topic':topic['prompt'],'poem':readable['poem']})
   mapping.append({'blind_id':bid,'job':j['key'],'arm':j['arm'],'selected':bool(selected)})
  rows.append({**j,'status':r['status'],'output':bool(selected),'full_basic_meter_pass':bool(selected) and selected['checks']['meter']['status']=='pass',
    'meter_unknown':bool(selected) and selected['checks']['meter']['status']=='unknown',
    'allusion_required':bool(topic.get('allusion_required')),'allusion_proxy_pass':bool(selected) and bool((read.get('allusion') or {}).get('supported')),
    'model_keep':bool(selected) and read.get('decision')=='keep','budget':budget,'generation_count':r.get('completed_generations')})
 by_arm={}
 for arm in binding['arms']:
  rs=[r for r in rows if r['arm']==arm];n=len(rs);times=sorted(r['budget'].get('elapsed_seconds',0) for r in rs)
  req=[r for r in rs if r['allusion_required']]
  both=[]
  for tid in {j['topic_id'] for j in jobs}:
   tr=[r for r in rs if r['topic_id']==tid]
   expected=sum(j['arm']==arm and j['topic_id']==tid for j in jobs)
   if len(tr)==expected:both.append(all(r['output'] for r in tr))
  by_arm[arm]={'expected_runs':sum(j['arm']==arm for j in jobs),'terminal_runs':n,
   'selected_outputs':sum(r['output'] for r in rs),'no_output_runs':sum(not r['output'] for r in rs),
   'full_basic_meter_pass':sum(r['full_basic_meter_pass'] for r in rs),'meter_unresolved':sum(r['meter_unknown'] for r in rs),
   'allusion_required_runs':len(req),'allusion_proxy_pass_on_required':sum(r['allusion_proxy_pass'] for r in req),
   'model_keep_proxy':sum(r['model_keep'] for r in rs),
   'topics_with_all_repetitions_finished':len(both),'topics_with_output_on_every_repetition':sum(both),
   'calls':sum(r['budget'].get('calls',0) for r in rs),'known_tokens':sum(r['budget'].get('tokens',0) for r in rs),
   'usage_unknown_calls':sum(r['budget'].get('usage_unknown_calls',0) for r in rs),
   'median_seconds':statistics.median(times) if times else None,
   'p90_seconds':times[max(0,math.ceil(.9*len(times))-1)] if times else None}
 random.Random(binding['experiment_sha256']).shuffle(blind)
 atomic_write(directory/'blind-packet.json',blind)
 atomic_write(directory/'blind-mapping-private.json',mapping)
 reading_path=directory/'assistant-blind-review.json'
 reading_status={'status':'pending','reviewer':'assistant, not user','proxy_is_not_human_preference':True}
 if reading_path.exists():
  submitted=json.loads(reading_path.read_text(encoding='utf-8'))
  packet=json.loads((directory/'blind-packet.json').read_text(encoding='utf-8'))
  mapping=json.loads((directory/'blind-mapping-private.json').read_text(encoding='utf-8'))
  poems={p['id']:p['poem'] for p in packet};notes=submitted['readings']
  if len(notes)!=len(poems) or {n['blind_id'] for n in notes}!=set(poems):raise ValueError('incomplete assistant blind reading')
  by_id={n['blind_id']:n for n in notes}
  for n in notes:
   if type(n['score']) is not int or not 0<=n['score']<=4 or n['worth_keeping']!=(n['score']>=2):raise ValueError('invalid blind score')
   if not n['quoted_evidence'] or any(not any(q in line for line in poems[n['blind_id']]['lines']) for q in n['quoted_evidence']):raise ValueError('invalid assistant quote')
  reading_status={'status':'complete','reviewer':submitted.get('reviewer','assistant'),'poems_read':len(notes),'user_preference_verified':False}
  for arm in binding['arms']:
   ms=[m for m in mapping if m['arm']==arm]
   by_arm[arm]['assistant_blind_worth_any_recorded_draft']=sum(by_id[m['blind_id']]['worth_keeping'] for m in ms)
   by_arm[arm]['assistant_blind_worth_selected_output']=sum(by_id[m['blind_id']]['worth_keeping'] and m['selected'] for m in ms)
   by_arm[arm]['assistant_blind_score_histogram']={str(i):sum(by_id[m['blind_id']]['score']==i for m in ms) for i in range(5)}
 pair_path=directory/'paired-blind-summary.json';paired=json.loads(pair_path.read_text(encoding='utf-8')) if pair_path.exists() else None
 audit_path=directory/'mechanical-audit.json';audit=json.loads(audit_path.read_text(encoding='utf-8')) if audit_path.exists() else None
 result={'expected_runs':len(jobs),'terminal_runs':len(rows),'missing_jobs':missing,'complete':not missing,
  'requested_model':binding['model'],'by_arm':by_arm,
  'model_paired_blind':{k:v for k,v in (paired or {}).items() if k!='pairs'},
  'mechanical_audit':{k:v for k,v in (audit or {}).items() if k!='rows'},
  'assistant_blind_reading':reading_status,
  'stability_proven':False,
  'limits':['本轮五绝、七绝和给定典源；不能外推任意题材、律诗或词',
    '两流程资源上限相同，实际资源消耗不同；不属于等算力对照',
    '读音待核不计入全谱确认，模型语义判断不等于已认证',
    '失败和未出稿始终留在分母，不能只比较最好几首',
    '模型盲评不是用户偏好验证；稳定性结论需结合实际诗作与独立阅读']}
 atomic_write(directory/'descriptive-report.json',result)
 lines=['古诗演化对照｜描述性报告','',f"完成 {len(rows)}/{len(jobs)} 次流程；模型请求名称：{binding['model']}。",'']
 for arm,s in by_arm.items():
  lines += [arm,f"出稿 {s['selected_outputs']}/{s['terminal_runs']}；未出稿 {s['no_output_runs']}。",
   f"所选基本谱全确认 {s['full_basic_meter_pass']}；仍待核音 {s['meter_unresolved']}。",
   f"用典专项：{s['allusion_proxy_pass_on_required']}/{s['allusion_required_runs']} 次由模型判定用典成立，尚不是人工核验。",
   f"调用 {s['calls']}；已知tokens {s['known_tokens']}；usage未知调用 {s['usage_unknown_calls']}。",
   f"单次中位耗时 {s['median_seconds']} 秒；经验90分位 {s['p90_seconds']} 秒。",'']
 if paired:lines += ['交换顺序的模型盲评：'+json.dumps(paired['literary_wins'],ensure_ascii=False),'']
 lines += ['文学盲读状态：'+reading_status['status']+'；不以模型keep代理人工阅读。','',*result['limits']]
 (directory/'统计与局限.txt').write_text('\n'.join(lines),encoding='utf-8')
 return result
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('directory',type=Path);a=p.parse_args();r=report(a.directory);print(json.dumps({'complete':r['complete'],'terminal_runs':r['terminal_runs'],'by_arm':r['by_arm']},ensure_ascii=False))
