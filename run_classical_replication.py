"""Exact frozen-protocol replication, retaining the failed batch and account deferrals."""
import argparse,concurrent.futures,copy,hashlib,json,re,sys,threading
from datetime import datetime,timezone
from pathlib import Path
from check_deepseek_balance import query_balance
from run_classical_fresh_validation import execute_job,ROOT
from experiments.classical_evolution.store import digest,code_digest
from poetry_agent.client import DeepSeekClient,load_env
from poetry_agent.style.corpus import write as atomic_write

def register(directory,replication_id):
    if not re.fullmatch('[a-z0-9-]{1,40}',replication_id):raise ValueError('invalid replication id')
    original=ROOT/'runs/classical-evolution-fresh-held-02/experiment-binding.json'
    source=json.loads(original.read_text(encoding='utf-8'))
    freeze=json.loads((ROOT/'runs/classical-evolution-fresh-freeze-02.json').read_text(encoding='utf-8'))
    if digest({k:v for k,v in source.items() if k!='experiment_sha256'})!=source['experiment_sha256']:
        raise ValueError('original registration changed')
    if source['experiment_sha256']!=freeze['experiment_sha256'] or code_digest()!=freeze['core_code_sha256']:
        raise ValueError('frozen protocol changed')
    for name,expected in freeze['files'].items():
        if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=expected:raise ValueError('frozen file changed: '+name)
    binding=copy.deepcopy(source)
    binding.update(role='independent exact-protocol replication after service402; not new unseen topics',
        parent_experiment_sha256=source['experiment_sha256'],replication_id=replication_id,
        replication_driver_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        balance_check_source_sha256=hashlib.sha256((ROOT/'check_deepseek_balance.py').read_bytes()).hexdigest(),
        account_policy='Read-only account availability before each unstarted job; unavailable jobs deferred without generating a poem; at most four already-running tasks can remain in flight.',
        prior_outcomes='All24 prior results and failures retained in fresh-held-02; no selective replacement.',
        exposure_note='Six prior readable poems reviewed by assistant; generator unchanged and no review feedback enters requests. Conditional operational replication, not a new unseen-topic success claim.')
    binding['jobs']=[{**j,'origin_job':j['key'],'key':replication_id+'-'+j['key']} for j in source['jobs']]
    binding.pop('experiment_sha256');binding['experiment_sha256']=digest(binding)
    directory.mkdir(parents=True,exist_ok=True);file=directory/'experiment-binding.json'
    if file.exists():
        if json.loads(file.read_text(encoding='utf-8'))!=binding:raise ValueError('replication registration changed')
    else:
        if any(directory.iterdir()):raise ValueError('nonempty unbound directory')
        atomic_write(file,binding)
    return binding

def run_one(binding,directory,job,unavailable,*,client_factory=DeepSeekClient,balance_fn=query_balance):
    if (directory/'jobs'/job['key']/'result.json').exists():return {'job':job['key'],'state':'existing'}
    if unavailable.is_set():return {'job':job['key'],'state':'deferred','reason':'account_unavailable_in_this_invocation'}
    client=client_factory(model=binding['model']);balance=balance_fn(client)
    folder=directory/'balance-checks'/job['key'];folder.mkdir(parents=True,exist_ok=True)
    atomic_write(folder/f'{len(list(folder.glob("*.json")))+1:03d}.json',balance)
    if balance.get('is_available') is not True:
        unavailable.set();return {'job':job['key'],'state':'deferred','reason':'account_preflight_not_available'}
    execute_job(binding,directory,job,client)
    return {'job':job['key'],'state':'finished'}

def main():
    sys.stdout.reconfigure(encoding='utf-8');p=argparse.ArgumentParser()
    p.add_argument('--out',type=Path,required=True);p.add_argument('--replication-id',required=True)
    p.add_argument('--prepare-only',action='store_true');p.add_argument('--workers',type=int,choices=[1,2,3,4],default=4);a=p.parse_args()
    binding=register(a.out,a.replication_id)
    if a.prepare_only:print('registered_exact_replication',len(binding['jobs']));return
    load_env(ROOT.parent/'poetry-agent/.env');unavailable=threading.Event();rows=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=a.workers) as pool:
        futures={pool.submit(run_one,binding,a.out,j,unavailable):j for j in binding['jobs']}
        for f in concurrent.futures.as_completed(futures):
            try:row=f.result()
            except Exception as exc:row={'job':futures[f]['key'],'state':'driver_error','error_type':type(exc).__name__}
            rows.append(row)
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    summary={'rows':rows,'terminal_results':len(list((a.out/'jobs').glob('*/result.json'))),'expected':24,
        'account_deferrals':sum(x['state']=='deferred' for x in rows),'prior_failed_batch_retained':True}
    atomic_write(a.out/'driver-invocations'/(stamp+'.json'),summary);atomic_write(a.out/'driver-summary.json',summary)
    print('terminal_replication_runs',summary['terminal_results'],'/24; deferred',summary['account_deferrals'],flush=True)

if __name__=='__main__':main()
