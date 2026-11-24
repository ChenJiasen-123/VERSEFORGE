"""Shared request deadline and call ceiling across the complete studio workflow."""
import time

class BudgetedClient:
    def __init__(self,client,seconds=240,max_calls=36):
        if type(max_calls) is not int or max_calls<1 or isinstance(seconds,bool) or seconds<=0:
            raise ValueError('总预算无效')
        self.client=client;self.seconds=seconds;self.max_calls=max_calls
        self.started=time.monotonic();self.calls=0
        self.model=client.model;self.mock=getattr(client,'mock',False)

    def complete(self,system,user,**kwargs):
        remaining=self.seconds-(time.monotonic()-self.started)
        if self.calls>=self.max_calls or remaining<=0:raise RuntimeError('全程模型预算已用尽')
        self.calls+=1
        kwargs['timeout']=min(kwargs.get('timeout',60),remaining)
        return self.client.complete(system,user,**kwargs)

    def summary(self):
        elapsed=time.monotonic()-self.started
        return {'calls':self.calls,'max_calls':self.max_calls,'elapsed_seconds':round(elapsed,3),
                'budget_seconds':self.seconds,'exhausted':self.calls>=self.max_calls or elapsed>=self.seconds,
                'scope':'all_model_calls_not_queue_wait_or_ui_delivery'}
