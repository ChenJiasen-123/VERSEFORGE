"""One bounded independent editorial cycle; preserves evidence and prior text."""
import json
from dataclasses import asdict
from .aesthetics import review,compare_bidirectional,failure_code
from .core import SYSTEM,MODERN_AESTHETIC,CLASSICAL_AESTHETIC,Poem,check
from .requirement_checks import safe_review
from .editor_selection import select_revision


def edit_once(prompt,poem,task,requirements,client):
    result={'original':poem,'poem':poem,'drafts':[poem],'adopted':False,
            'protocol':'independent-editor-0.1','quality_verified':False}
    try:
        result['review']=review(poem,asdict(task),client,60)
        if result['review']['assessment']['decision']=='keep':
            result['status']='no_revision_requested'
            return result
        payload={'task':asdict(task),'revision':{'draft':poem,'editor':result['review']['assessment'],
            'instruction':'处理最重要的问题，保护已成立的语言、声音和全篇关系；不要为了顺滑把陌生表达改成说明。遵守原题全部硬要求。'},'original_prompt':prompt}
        response=client.complete(SYSTEM+(MODERN_AESTHETIC if task.genre=='modern' else CLASSICAL_AESTHETIC),
            json.dumps(payload,ensure_ascii=False),timeout=90,max_tokens=8192,
            thinking='disabled' if task.genre=='modern' else 'enabled')
        revised=asdict(Poem.parse(response['content']));result['drafts'].append(revised)
        result['hard_issues']=check(Poem(**revised),task)
        result['requirements']=safe_review(prompt,revised,requirements,client)
        if result['hard_issues'] or not result['requirements']['confirmed']:
            result['status']='revision_constraints_unconfirmed'
            return result
        result['revision_review']=review(revised,asdict(task),client,60)
        if result['revision_review']['assessment']['decision']!='keep':
            result['status']='revision_still_needs_editing'
            return result
        result['comparison']=compare_bidirectional(poem,revised,asdict(task),client,60,relation='revision')
        result['selection']=select_revision(poem,revised,hard_issues=result['hard_issues'],
            requirements=result['requirements'],literary_review=result['revision_review'],comparison=result['comparison'])
        result['poem']=result['selection']['poem'];result['adopted']=result['selection']['adopted']
        result['status']='revision_selected' if result['adopted'] else 'original_retained'
    except (ValueError,RuntimeError,KeyError,TypeError) as exc:
        result['status']='editor_incomplete';result['failure_code']=failure_code(exc)
    return result
