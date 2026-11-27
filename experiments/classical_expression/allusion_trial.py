"""Paired allusion diagnostic, not a new GA or a proof of general improvement."""
import json
from dataclasses import asdict
from .run import ROOT,Transport,Adapter,save
from .selection import bind_run,fingerprint
from .protocol import review
from poetry_agent.client import DeepSeekClient,load_env
from poetry_agent.core import Task,Poem,check,_metrical_target_and_report
from poetry_agent.qijue_profiles import specification
from experiments.reverse_prompt_engineering.llm import Budget,LLM,LLMCache,JsonlLedger,restore_budget_from_ledger

TOPICS=[
 ('01','写一首七绝：一个人拒绝一份令人羡慕的安排，回到自己的日常。不可直接使用自由、富贵、归隐三个词。'),
 ('02','写一首七绝：一个人急需眼前的小帮助，却得到关于将来的大许诺。不得出现承诺、讽刺两词，不直接评价人物品德。'),
 ('03','写一首七绝：一件曾经帮助人成长的日常器物，如今已不再适用。诗题标注器物，不以感叹岁月流逝作结。')]
SYSTEM='''你是古典诗作者。先决定要触及的体验或判断，再组织全诗。
允许白描、议论、直抒、反问，不强制身体动作、沉默、温度或物象收尾。
用典应承担推理、价值选择、反讽或情绪关系，不能仅以古雅词代替普通词。
典故可明用、暗用或翻用；翻用须清楚原义与新作立场。出处不确定则不用。
只返回JSON：{"title":"诗题","lines":["四句各七字"],"intention":"表达对象",
"allusion":{"card_id":"无则空串","mode":"明用/暗用/翻用/不用","relation":"典源与本诗的对应，新增或改变什么意思；不使用则说明理由"}}。
不得照抄参考名句。谱中P平Z仄，按指定基本谱与平水韵写。'''

def main():
    root=ROOT/'allusion-study-01';out=root/'runs/paired-01';out.mkdir(parents=True,exist_ok=True)
    bind_run(out/'binding.json',{'source':fingerprint([__import__('pathlib').Path(__file__)]),
        'cards':fingerprint([root/'cards.json']),'topics':TOPICS,'budget_calls':80,'budget_tokens':300000})
    load_env(ROOT.parents[2]/'poetry-agent/.env')
    budget=Budget(80,300000);restore_budget_from_ledger(budget,out/'ledger.jsonl')
    llm=LLM(Transport(DeepSeekClient()),budget,LLMCache(out/'cache.jsonl'),JsonlLedger(out/'ledger.jsonl'),max_parse_retries=1)
    cards=json.loads((root/'cards.json').read_text(encoding='utf8'))['cards']
    for ident,prompt in TOPICS:
        task=Task(prompt,'qijue',4,qijue_pattern='ping_rhyme')
        for group in ('open','source_guided'):
            path=out/(ident+'-'+group+'.json')
            if path.exists():continue
            print(ident+' '+group,flush=True)
            payload={'prompt':prompt,'metrical_target':specification('ping_rhyme'),
                'method':'独立探索表达方式，可用典也可不用，不提供典故资料。' if group=='open' else '比较可用典故承载的表达关系，适切才使用，不为典故硬造经历。',
                'source_cards':[] if group=='open' else cards}
            drafts=[];current=None
            for round_no in range(3):
                if current:
                    payload['revision']={'draft':current['poem'],'blind_reading':current['blind']['data'],
                        'formal_report':current['meter'],'instruction':'先修明确错误，再修表达缺口。读音未知不叫错误；不要只添典故名。'}
                data,meta=llm.call_json(purpose='allusion_generate',system=SYSTEM,
                    user=json.dumps(payload,ensure_ascii=False),max_tokens=4096,thinking='disabled',
                    cache_variant=f'{ident}-{group}-{round_no}')
                poem=asdict(Poem.parse(json.dumps(data,ensure_ascii=False)))
                blind=review(prompt,poem,llm)
                target,meter=_metrical_target_and_report(poem,task)
                current={'poem':poem,'intention':data.get('intention'),'allusion_claim':data.get('allusion'),
                    'blind':blind,'hard_issues':check(Poem(**poem),task),'meter':meter,'response_meta':meta}
                drafts.append(current)
                save(out/(ident+'-'+group+'-checkpoint.json'),{'drafts':drafts,'status':'in_progress'})
                if not current['hard_issues'] and blind['data']['decision']=='keep':break
            # Preserve all drafts; this diagnostic does not claim a literary winner.
            selected=min(drafts,key=lambda d:(len(d['hard_issues']),d['blind']['data']['decision']!='keep'))
            save(path,{'prompt':prompt,'group':group,'drafts':drafts,'selected':selected,
                'allusion_accuracy_independently_verified':False,'quality_verified':False})
    save(out/'summary.json',{'status':'generated_six_pairs_pending_analysis','poems':6,'budget':budget.summary(),
        'limitations':['三题为适合典故的定向诊断，非泛化测试','open组也允许自行用典','生成与审读同模型家族','尚待典故贴切性、题意与读音独立核验']})

if __name__=='__main__':main()
