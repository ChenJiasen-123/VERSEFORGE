"""Read-only official balance preflight; never print credentials or balance amounts."""
import argparse,json,sys,urllib.request,urllib.error
from datetime import datetime,timezone
from pathlib import Path
from poetry_agent.client import DeepSeekClient,load_env,NoRedirect

ENDPOINT='https://api.deepseek.com/user/balance'
DOCUMENTATION='https://api-docs.deepseek.com/zh-cn/api/get-user-balance/'

def query_balance(client,opener=None):
    request=urllib.request.Request(ENDPOINT,headers={'Authorization':'Bearer '+client.key},method='GET')
    out={'checked_utc':datetime.now(timezone.utc).isoformat(),'endpoint':ENDPOINT,'documentation':DOCUMENTATION}
    try:
        with (opener or urllib.request.build_opener(NoRedirect())).open(request,timeout=20) as response:
            data=json.load(response)
        if not isinstance(data,dict) or type(data.get('is_available')) is not bool:
            raise ValueError('invalid balance response')
        out.update(status='available' if data['is_available'] else 'unavailable',is_available=data['is_available'])
    except urllib.error.HTTPError as e:out.update(status='error',http_status=e.code)
    except (urllib.error.URLError,TimeoutError,OSError):out.update(status='error',failure='connection_failed')
    except (ValueError,TypeError):out.update(status='error',failure='invalid_balance_response')
    return out

def main():
    sys.stdout.reconfigure(encoding='utf-8');p=argparse.ArgumentParser()
    p.add_argument('--env-file',type=Path,default=Path(__file__).resolve().parent.parent/'poetry-agent/.env')
    p.add_argument('--out',type=Path);a=p.parse_args();load_env(a.env_file)
    result=query_balance(DeepSeekClient())
    if a.out:a.out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))
    return 0 if result.get('is_available') is True else 2

if __name__=='__main__':raise SystemExit(main())
