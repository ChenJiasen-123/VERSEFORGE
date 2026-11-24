"""One bounded independent editorial cycle; preserves evidence and prior text."""
import json
import time
from dataclasses import asdict,replace
from .aesthetics import review,compare_bidirectional,failure_code
from .core import SYSTEM,MODERN_AESTHETIC,CLASSICAL_AESTHETIC,Poem,check,_metrical_target_and_report
from .requirement_checks import safe_review
from .editor_selection import select_revision,compliance_repair_priority
from .proofreading import proofread


def edit_once(prompt,poem,task,requirements,client,*,proofread_text=False):
    result={'original':poem,'poem':poem,'drafts':[poem],'adopted':False,
            'protocol':'independent-editor-0.1','quality_verified':False}
    upstream=client
    result['model_responses']=[]
    class Recorder:
        def complete(self,system,user,**kwargs):
            response=upstream.complete(system,user,**kwargs)
            result['model_responses'].append({'content':response.get('content',''),
                'usage':response.get('usage',{}),'request_settings':response.get('request_settings',{})})
            return response
    client=Recorder()
    # Review the text against the user prompt, not the writer's rationale.
    review_task={'topic':prompt,'genre':task.genre,'max_lines':task.max_lines}
    try:
        copy_issues=[]
        if proofread_text and task.genre=='modern':
            result['proofreading']=proofread(poem,client)
            copy_issues=result['proofreading']['issues']
        original_meter=_metrical_target_and_report(poem,task) if task.genre!='modern' else None
        if original_meter is not None:result['original_meter']=original_meter[1]
        result['original_requirements']=safe_review(prompt,poem,requirements,client)
        if copy_issues:
            result['review']={'assessment':{'decision':'revise','preserve':'原有正文语义与语言关系',
                'problem':'独立校对提出文字问题，先作最小修复并复核。','suggestion':'仅处理copyediting_suggestions，不扩写。',
                'tradeoff':'避免连带改变原有文字。'},'source':'copyediting_priority_not_literary_review'}
        else:
            result['review']=review(poem,review_task,client,60)
        known_conflicts=bool(result['original_requirements'].get('violations') or result['original_requirements'].get('repair_requests')
                             or (original_meter and original_meter[1]['status']=='failed'))
        if result['review']['assessment']['decision']=='keep' and not known_conflicts and not copy_issues:
            result['status']='no_revision_requested'
            return result
        payload={'task':asdict(task),'revision':{'draft':poem,'editor':result['review']['assessment'],
            'instruction':'处理最重要的问题，保护已成立的语言、声音和全篇关系；不要为了顺滑把陌生表达改成说明。遵守原题全部硬要求。'},'original_prompt':prompt}
        payload['revision']['original_requirement_report']=result['original_requirements']
        payload['revision']['copyediting_suggestions']=copy_issues
        if task.genre != 'modern':
            initial_meter=original_meter
            if initial_meter is not None:
                payload['metrical_target']=initial_meter[0]
                result['original_meter']=initial_meter[1]
                payload['revision']['meter_report']=initial_meter[1]
        response=client.complete(SYSTEM+(MODERN_AESTHETIC if task.genre=='modern' else CLASSICAL_AESTHETIC),
            json.dumps(payload,ensure_ascii=False),timeout=90,max_tokens=8192,
            thinking='disabled' if task.genre=='modern' else 'enabled')
        revised=asdict(Poem.parse(response['content']));result['drafts'].append(revised)
        result['hard_issues']=check(Poem(**revised),task)
        if task.genre != 'modern':
            final_meter=_metrical_target_and_report(revised,task)
            result['revision_meter']=final_meter[1] if final_meter is not None else None
            if final_meter is None or final_meter[1].get('status')!='pass':
                result['status']='revision_meter_failed' if final_meter and final_meter[1].get('status')=='failed' else 'revision_meter_unconfirmed'
                result['meter_next_action']='修复明确平仄或押韵错误，保留已通过位置；读音不确定不是失律，不为过谱自行选音。' if result['status']=='revision_meter_failed' else '现有字表或语境读音不足以确认。可自然重组句意，但不要用生僻替字制造新的缺字，也不要将未确认称作错误。'
                return result
        result['requirements']=safe_review(prompt,revised,requirements,client)
        if result['hard_issues'] or not result['requirements']['confirmed']:
            result['status']='revision_constraints_unconfirmed'
            return result
        if proofread_text and task.genre=='modern':
            result['revision_proofreading']=proofread(revised,client)
            if result['revision_proofreading']['issues']:
                result['status']='revision_copyediting_unresolved'
                return result
            # A punctuation-only repair need not compete aesthetically with a typo.
            import re
            letters=lambda p:re.sub(r'[^\w]','',''.join(p['lines']))
            if copy_issues and poem['title']==revised['title'] and letters(poem)==letters(revised):
                result['poem']=revised;result['adopted']=True
                result['status']='copyedit_repair_selected'
                return result
        if compliance_repair_priority(result['original_requirements'],result['requirements'],result['hard_issues']):
            result['poem']=revised;result['adopted']=True
            result['status']='compliance_repair_selected'
            return result
        result['revision_review']=review(revised,review_task,client,60)
        if result['revision_review']['assessment']['decision']!='keep':
            result['status']='revision_still_needs_editing'
            return result
        result['comparison']=compare_bidirectional(poem,revised,review_task,client,60,relation='revision')
        result['selection']=select_revision(poem,revised,hard_issues=result['hard_issues'],
            requirements=result['requirements'],literary_review=result['revision_review'],comparison=result['comparison'])
        result['poem']=result['selection']['poem'];result['adopted']=result['selection']['adopted']
        result['status']='revision_selected' if result['adopted'] else 'original_retained'
    except (ValueError,RuntimeError,KeyError,TypeError) as exc:
        result['status']='editor_incomplete'
        result['failure_code']='editor_budget_exhausted' if str(exc) in ('编辑预算已用尽','全程模型预算已用尽') else failure_code(exc)
    return result


def edit_rounds(prompt,poem,task,requirements,client,*,max_rounds=3,max_calls=18,budget_seconds=180):
    if not 1 <= max_rounds <= 8 or max_calls < 1 or budget_seconds <= 0:
        raise ValueError('编辑预算无效')
    started=time.monotonic();calls=0
    class BudgetClient:
        def complete(self,system,user,**kwargs):
            nonlocal calls
            remaining=budget_seconds-(time.monotonic()-started)
            if calls>=max_calls or remaining<=0:
                raise RuntimeError('编辑预算已用尽')
            calls+=1
            kwargs['timeout']=min(kwargs.get('timeout',60),remaining)
            return client.complete(system,user,**kwargs)
    selected=poem;rounds=[];drafts=[poem];feedback='';stop='round_limit'
    for number in range(max_rounds):
        if calls>=max_calls or time.monotonic()-started>=budget_seconds:
            stop='budget_exhausted';break
        current_task=replace(task,extra_requirements=task.extra_requirements+feedback)
        row=edit_once(prompt,selected,current_task,requirements,BudgetClient(),proofread_text=True)
        rounds.append(row);drafts.extend(row['drafts'][1:])
        if row.get('failure_code')=='editor_budget_exhausted':
            stop='budget_exhausted';break
        if row['adopted']:
            selected=row['poem']
        if row['status']=='no_revision_requested':
            stop='editor_keep';break
        feedback='\n上轮自动编辑记录（不是新增题目要求）：'+json.dumps({
            'status':row['status'],'review':row.get('review',{}).get('assessment'),
            'requirements':row.get('requirements'),'hard_issues':row.get('hard_issues'),
            'meter':row.get('revision_meter'),'comparison':row.get('comparison',{}).get('assessment'),
            'meter_next_action':row.get('meter_next_action'),
            'rejected_draft':row['drafts'][-1] if not row['adopted'] else None},ensure_ascii=False)
    return {'original':poem,'poem':selected,'drafts':drafts,'rounds':rounds,
            'adopted':selected!=poem,'status':stop,'calls':calls,
            'elapsed_seconds':round(time.monotonic()-started,3),
            'protocol':'automatic-editor-0.1','quality_verified':False}
