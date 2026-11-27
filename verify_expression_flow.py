import json, hashlib, time, sys
sys.stdout.reconfigure(encoding="utf-8")
from datetime import datetime, timezone
from pathlib import Path
from poetry_agent.client import DeepSeekClient, load_env
from poetry_agent.recording_client import RecordingClient
from poetry_agent.studio import run_studio
root=Path(__file__).resolve().parent
load_env(root/'.env')
out=root/'research'/('expression-flow-live-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
out.mkdir(parents=True,exist_ok=True)
base=DeepSeekClient()
metadata={'started_utc':datetime.now(timezone.utc).isoformat(),'key_fingerprint_sha256':hashlib.sha256(base.key.encode()).hexdigest()[:16], 'base_url':base.base,'requested_model':base.model,'max_calls':24,'max_seconds':300,'prompt':'写一首七绝，题为《旧钥匙》。正文不得出现“钥匙”二字，只能通过形、声、用、痕写出器物。'}
metadata['source_sha256']={name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in ('poetry_agent/studio.py','poetry_agent/expression_plan.py','poetry_agent/allusion_policy.py','poetry_agent/requirement_checks.py','poetry_agent/editor.py','poetry_agent/client.py')}
(out/'metadata.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
client=RecordingClient(base,out/'responses.json')
try:
 result=run_studio(metadata['prompt'],client=client,candidate_count=2,independent_editor=True,total_max_calls=24,total_budget_seconds=300,progress=lambda phase:print(phase,flush=True))
 (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({'status':result['status'],'poem':result['poem'],'budget':result['runtime_budget']},ensure_ascii=False),flush=True)
except Exception as exc:
 (out/'failure.json').write_text(json.dumps({'type':type(exc).__name__,'message':str(exc)},ensure_ascii=False),encoding='utf-8')
 print(type(exc).__name__,str(exc),flush=True)
finally:
 print('saved_records',len(client.records),flush=True)
