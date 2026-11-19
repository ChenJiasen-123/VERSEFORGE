import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse


def load_env(path):
    """Small .env loader: KEY=value only; shell expressions are never executed."""
    if not Path(path).exists():
        return
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        os.environ.setdefault(name.strip(), value.strip().strip("\"'"))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class DeepSeekClient:
    mock = False

    def __init__(self):
        self.key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
        self.model = os.environ.get("DEEPSEEK_MODEL", "deepseek-flash").strip()
        self.base = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
        parsed = urlparse(self.base)
        if parsed.scheme != "https" or parsed.hostname != "api.deepseek.com" or parsed.port not in (None, 443) or parsed.username or parsed.query or parsed.fragment or parsed.path not in ("", "/v1"):
            raise ValueError("接口地址仅允许https://api.deepseek.com或其/v1路径，防止密钥发往其他站点")
        if not self.key:
            raise ValueError("未配置DEEPSEEK_API_KEY，请在项目.env中填写，或先用--mock体验")

    def complete(self, system, user, timeout, max_tokens=4096, thinking=None):
        payload = {"model": self.model, "messages": [
            {"role": "system", "content": system}, {"role": "user", "content": user}],
            "stream": False, "max_tokens": max_tokens}
        payload['response_format'] = {'type': 'json_object'}
        if thinking is not None:
            if thinking not in ('enabled', 'disabled'):
                raise ValueError('thinking须为enabled或disabled')
            payload['thinking'] = {'type': thinking}
        request = urllib.request.Request(self.base + "/chat/completions",
            data=json.dumps(payload).encode("utf-8"), headers={
                "Content-Type": "application/json", "Authorization": "Bearer " + self.key})
        try:
            opener = urllib.request.build_opener(NoRedirect())
            with opener.open(request, timeout=min(timeout, 90)) as response:
                data = json.load(response)
            choice = data["choices"][0]
            if choice.get("finish_reason") != "stop":
                reason = choice.get('finish_reason')
                code = reason if reason in ('length', 'content_filter', 'tool_calls') else 'unknown'
                raise RuntimeError(f"模型输出未正常结束（{code}），本次输出未采用")
            content = choice["message"].get("content")
            if not isinstance(content, str) or not content.strip():
                raise RuntimeError("模型返回空正文")
            return {"content": content, "usage": data.get("usage", {}),
                    'request_settings': {'max_tokens': max_tokens, 'response_format': 'json_object',
                                         'thinking': thinking or 'service_default'}}
        except urllib.error.HTTPError as exc:
            hints = {401: "密钥无效", 402: "余额不足", 429: "请求限流", 400: "检查模型名称或请求参数"}
            raise RuntimeError(f"DeepSeek HTTP {exc.code}：{hints.get(exc.code, '请求失败，请检查服务状态')}（未自动重试）") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise RuntimeError("网络连接失败或超时；请确认网络后重试") from None
        except (KeyError, IndexError, TypeError, ValueError):
            raise RuntimeError("模型服务返回了无法解析的响应") from None


class MockClient:
    mock = True
    model = "mock-demo-not-deepseek"

    def complete(self, system, user, timeout):
        task = json.loads(user)["task"]
        if task['genre'] == 'wulv':
            lines = ['暮雨侵苔徑', '疏燈照客衣', '寒窗聞葉落', '倚戶待人歸'] * 2
        elif task['genre'] == 'qilv':
            lines = ['细雨初收山色新', '溪桥流水过前村', '东风吹绿田间草', '燕子归来又一春'] * 2
        elif task['genre'] == 'wujue':
            lines = ['暮雨侵苔徑', '疏燈照客衣', '寒窗聞葉落', '倚戶待人歸']
        elif task["genre"] == "qijue":
            lines = ["细雨初收山色新", "溪桥流水过前村", "东风吹绿田间草", "燕子归来又一春"]
        else:
            lines = ["长江把夜色推向岸边", "他摘下手套，掌心留着机器的温度", "换班的灯亮了", "一只饭盒接住清晨"]
        return {"content": json.dumps({"title": "模拟作品（非模型生成）", "lines": lines}, ensure_ascii=False), "usage": {}}
