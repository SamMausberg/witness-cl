"""Bounded untrusted LLM proposal input; only finite typed programs, never code."""
from __future__ import annotations
import json
from .latent import Program, validate_program


def parse_program(text: str, *, actions: int, outputs: int, horizon: int,
                  max_bytes: int = 32768) -> Program:
    if not isinstance(text,str) or len(text.encode('utf-8'))>max_bytes:
        raise ValueError('proposal exceeds text budget')
    if any(type(v) is not int or v<1 for v in (actions,outputs,horizon)) or horizon>12:
        raise ValueError('invalid public dimensions')
    if sum(outputs**t for t in range(horizon))>100000:
        raise ValueError('history tree exceeds node cap')
    def unique_pairs(pairs):
        result={}
        for k,v in pairs:
            if k in result:raise ValueError('duplicate JSON field')
            result[k]=v
        return result
    try:
        obj=json.loads(text,object_pairs_hook=unique_pairs)
    except (TypeError,json.JSONDecodeError,RecursionError) as e:
        raise ValueError('invalid bounded JSON program') from e
    if not isinstance(obj,dict):raise ValueError('one object required')
    if set(obj)=={'word'}:
        word=obj['word']
        if not isinstance(word,list) or len(word)!=horizon or any(type(a) is not int for a in word):
            raise ValueError('fixed-horizon integer action word required')
        p=Program.word(tuple(word),outputs)
    elif set(obj)=={'levels'}:
        levels=obj['levels']
        if not isinstance(levels,list) or len(levels)!=horizon or any(not isinstance(row,list) for row in levels):
            raise ValueError('one complete history tree required')
        p=Program(outputs,tuple(tuple(row) for row in levels))
    else:raise ValueError('only word OR levels is allowed; no code, reward or certificate fields')
    validate_program(p,actions,outputs)
    return p
