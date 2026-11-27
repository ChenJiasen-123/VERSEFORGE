"""Opt-in local experiment traces, excluding credentials and request headers."""
import json
from pathlib import Path
from .aesthetics import failure_code

class RecordingClient:
    def __init__(self,client,path):
        self.client=client;self.path=Path(path);self.model=client.model
        self.mock=getattr(client,'mock',False);self.records=[]
        if self.path.exists():raise ValueError('实验记录已存在，不覆盖')

    def save(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.path.write_text(json.dumps({'model':self.model,'records':self.records,
            'scope':'model_outputs_only_not_request_headers_or_credentials'},ensure_ascii=False,indent=2),encoding='utf-8')

    def complete(self,system,user,**kwargs):
        try:response=self.client.complete(system,user,**kwargs)
        except (ValueError,RuntimeError,KeyError,TypeError) as exc:
            self.records.append({'failure_code':failure_code(exc)});self.save();raise
        self.records.append({key:response[key] for key in ('content','usage','request_settings','response_metadata') if key in response})
        self.save()
        return response
