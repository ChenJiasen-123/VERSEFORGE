"""Development diagnostic on fixed old poems, without author plans or expected verdicts."""
import argparse, concurrent.futures, copy, hashlib, json, sys
from pathlib import Path
import classical_agent as entry
from experiments.classical_evolution.store import RecordedClient, RunStore, digest
from poetry_agent.client import DeepSeekClient, load_env

ROOT=Path(__file__).resolve().parent
CASES=['held-04-r2','held-09-r1','held-05-r2','held-10-r1','held-02-r1']

def main():
    sys.stdout.reconfigure(encoding='utf-8')
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True)
    p.add_argument('--limit',type=int,choices=[1,2,5],default=5);a=p.parse_args()
    load_env(ROOT.parent/'poetry-agent'/'.env')
    cases=[]
    for key in CASES[:a.limit]:
        folder=ROOT/'runs/classical-evolution-raw-held-01/jobs'/(key+'-raw_classical_evolution')
        r=json.loads((folder/'result.json').read_text(encoding='utf-8'))
        b=json.loads((folder/'kernel/binding.json').read_text(encoding='utf-8'))
        c={k:copy.deepcopy(r['selected'][k]) for k in ('id','poem','checks')}
        cases.append({'origin':key,'topic':b['topic'],'sources':b['sources'],'candidate':c})
    binding={'role':'development fixed-poem semantic-reader probe; not new held-out validation',
        'protocol':entry.VERSION,'entry_sha256':hashlib.sha256((ROOT/'classical_agent.py').read_bytes()).hexdigest(),
        'reader_policy':entry.CRITIC_POLICY,'cases':cases,'model':'deepseek-reasoner'}
    store=RunStore(a.out,binding)
    def execute(item):
        index,case=item;folder=a.out/f'case-{index:02d}'
        local=RunStore(folder,{'study':store.binding_hash,'case':digest(case)})
        done=local.load('result.json')
        if done:return done
        api=RecordedClient(DeepSeekClient(model=binding['model']),local,max_calls=3,seconds=120)
        proxy=entry.KernelClient(api)
        def stage(action):proxy.action=action
        engine=entry.IndividualEvolution(case['topic'],case['sources'],proxy,folder/'reader',
            config={'generations':0,'pairwise':False,'critic_policy':entry.CRITIC_POLICY},progress=stage)
        out=engine._read('read-probe',[case['candidate']])[0]
        result={'origin':case['origin'],'poem':case['candidate']['poem'],'review':out.get('review'),'budget':api.summary()}
        local.save('result.json',result)
        print('finished',index,'complete',bool(result['review']),flush=True)
        return result
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        rows=list(pool.map(execute,enumerate(cases)))
    store.save('summary.json',{'rows':rows,'complete_reviews':sum(bool(x['review']) for x in rows),
        'warning':'Old exposed development poems. Structured fields and model verdicts do not independently certify semantic correctness.'})

if __name__=='__main__':main()
