"""Readable lineage exports, leaving source generation records unchanged."""
import argparse,json,sys
from pathlib import Path
OPS={'initial':'初稿','crossover':'融合构思后整首重写','meter_repair':'修复明确声律冲突','topic_repair':'修复题意要求','allusion_rebuild':'重构用典','parallelism_repair':'修复对仗','diction_revision':'调整措辞与句法','perspective_change':'改变发话视角','expression_rebuild':'重构表达推进'}
def export(directory):
 b=json.loads((directory/'experiment-binding.json').read_text(encoding='utf-8'));out=directory/'演化过程';out.mkdir(exist_ok=True);index=[]
 for job in b['jobs']:
  if job['arm'] not in ('classical_evolution','raw_classical_evolution'):continue
  folder=Path(job.get('result_directory') or directory/'jobs'/job['key']);rp=folder/'result.json'
  if not rp.exists():continue
  r=json.loads(rp.read_text(encoding='utf-8'));kernel=folder/'kernel' if job['arm']=='raw_classical_evolution' else folder
  if not (kernel/'state.json').exists():continue
  state=json.loads((kernel/'state.json').read_text(encoding='utf-8'))
  topic=next(t for t in b['topics'] if t['id']==job['topic_id']);selected=(r.get('selected') or {}).get('id')
  lines=[topic['prompt'],'',f"最终状态：{r['status']}",f"最终采用稿：{selected or '未选出合格候选'}",'']
  for p in state['archive']:
   checks=p['checks'];reader=p.get('review') or {};change=p.get('change') or {}
   lines += [f"{p['id']}｜第{p['generation']}代｜{OPS.get(p['operator'],p['operator'])}",
    '来源稿：'+('、'.join(p['parent_ids']) or '独立构思'),p['poem']['title'],*p['poem']['lines'],'',
    '本代审读读到的体验：'+reader.get('experience','审读未完成'),
    '本代审读指出的问题：'+reader.get('problem','未完成'),
    '本代审读建议：'+reader.get('suggestion','未完成'),
    '改稿声明（作者自述）：'+change.get('changed','无'),
    '保留内容（作者自述）：'+change.get('preserved','无'),
    '明确硬问题：'+('；'.join(checks['hard_issues']) or '当前资料未检出'),
    '字表检查状态：'+checks['meter']['status'],'']
  if r.get('selected'):
   p=r['selected'];a=(p.get('review') or {}).get('allusion') or {};card=b['sources'].get(a.get('source_id'))
   lines += ['最终所选稿的独立审读：',p['review']['experience'],'尚存问题：'+p['review']['problem']]
   if card:lines += ['模型所指典源：'+card['title'],card['url'],'模型所指压缩作用：'+a['compression']]
  lines += ['','说明：作者构思与修改声明不作为正文已表达的证据。模型审读与评分仍可能误判。']
  path=out/(job['key']+'.txt');path.write_text('\n'.join(lines),encoding='utf-8');index += [job['key'],topic['prompt'],str(path.name),'']
 (out/'索引.txt').write_text('\n'.join(index),encoding='utf-8');return len(index)//4
if __name__=='__main__':
 sys.stdout.reconfigure(encoding='utf-8');p=argparse.ArgumentParser();p.add_argument('directory',type=Path);a=p.parse_args();print('exported',export(a.directory))
