"""Minimal local chat-completions client. No model or provider credentials bundled."""
from __future__ import annotations
from dataclasses import dataclass
import json
import os
import time
from urllib.parse import urlparse
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError, URLError

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError("HTTP redirects are disabled to avoid silently moving data")

@dataclass(frozen=True)
class Completion:
    content: str
    usage: dict | None
    seconds: float

class LocalChatClient:
    def __init__(self, base_url: str, model: str, *, allow_remote: bool = False,
                 max_tokens: int = 96, timeout: float = 120):
        url=urlparse(base_url)
        if url.scheme not in {"http","https"} or url.username or url.password:
            raise ValueError("use an HTTP(S) URL without embedded credentials")
        if not allow_remote and url.hostname not in {"localhost","127.0.0.1","::1"}:
            raise ValueError("remote endpoints require explicit allow_remote=True")
        if not model or max_tokens<1 or timeout<=0:
            raise ValueError("model, positive token cap and timeout required")
        self.url=base_url.rstrip('/')+'/chat/completions'
        self.model=model; self.max_tokens=max_tokens; self.timeout=timeout
        self.opener=build_opener(NoRedirect())

    def complete(self, system: str, user: str) -> Completion:
        data=json.dumps({"model":self.model,"temperature":0,"max_tokens":self.max_tokens,
            "messages":[{"role":"system","content":system},{"role":"user","content":user}]}).encode()
        headers={"Content-Type":"application/json"}
        key=os.environ.get("WITNESS_API_KEY")
        if key: headers["Authorization"]="Bearer "+key
        start=time.perf_counter()
        # No automatic retries, model substitutions, or hidden history truncation.
        try:
            with self.opener.open(Request(self.url,data=data,headers=headers),timeout=self.timeout) as response:
                result=json.load(response)
        except (HTTPError, URLError, TimeoutError) as exc:
            raise RuntimeError("model request failed; run aborted rather than scoring fabricated responses") from exc
        try: content=result["choices"][0]["message"]["content"]
        except (KeyError,IndexError,TypeError) as exc: raise ValueError("invalid chat response") from exc
        if not isinstance(content,str): raise ValueError("non-text completion")
        usage=result.get("usage")
        if usage is not None and not isinstance(usage,dict): raise ValueError("invalid usage object")
        return Completion(content,usage,time.perf_counter()-start)

def parse_action(text: str, modulus: int) -> int:
    """Invalid structured outputs are invalid actions, not a free retry or guess."""
    try: data=json.loads(text)
    except (ValueError,TypeError): return -1
    if not isinstance(data,dict) or set(data)!={"action"}: return -1
    action=data["action"]
    return action if type(action) is int and 0<=action<modulus else -1
