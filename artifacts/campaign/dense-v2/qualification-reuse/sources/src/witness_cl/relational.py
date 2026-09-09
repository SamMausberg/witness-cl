"""Schema-derived read-only relational skill DSL, with an independent SQLite oracle.

Grammar construction sees only public column types/names, never evaluator labels,
latent regime IDs, or reference queries. The supplied DSL is restricted: it is
not a complete SQL synthesizer or a natural-language semantic parser.
"""
from __future__ import annotations
from dataclasses import dataclass
from itertools import product
import hashlib
import json
import re
import sqlite3
from .adaptive import Rule

@dataclass(frozen=True)
class Column:
    name:str
    kind:str
    def __post_init__(self):
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',self.name) or self.kind not in ('int','bool'):
            raise ValueError('unsupported public column identifier/type')

@dataclass(frozen=True)
class Snapshot:
    columns:tuple[Column,...]
    rows:tuple[tuple[int|None,...],...]
    def __post_init__(self):
        if not isinstance(self.columns,tuple) or not all(isinstance(c,Column) for c in self.columns) or not isinstance(self.rows,tuple):
            raise ValueError('immutable typed schema and row tuples required')
        if not self.columns or len({c.name for c in self.columns})!=len(self.columns):
            raise ValueError('nonempty unique public schema required')
        for row in self.rows:
            if not isinstance(row,tuple) or len(row)!=len(self.columns):
                raise ValueError('ragged rows')
            for c,v in zip(self.columns,row):
                if v is not None and (not isinstance(v,int) or abs(v)>10**9):
                    raise ValueError('bounded nullable integer cells required')
                if c.kind=='bool' and v not in (None,0,1):
                    raise ValueError('Boolean domain violation')
        if len(self.rows)>10**6:
            raise ValueError('snapshot exceeds the reference resource bound')

    @property
    def schema_hash(self)->str:
        raw=json.dumps([(c.name,c.kind) for c in self.columns],separators=(',',':'))
        return hashlib.sha256(raw.encode()).hexdigest()

@dataclass(frozen=True)
class SumPlan:
    schema:tuple[Column,...]
    positive:int
    negative:int|None
    # For each bool column: 0 unrestricted, 1 equals 0, 2 equals 1,
    # 3 COALESCE(column,0)=0. SQL NULL semantics are explicit.
    filters:tuple[tuple[int,int],...]

    def __post_init__(self):
        if not 0<=self.positive<len(self.schema) or self.schema[self.positive].kind!='int':
            raise ValueError('positive term must reference a numeric column')
        if self.negative is not None and (not 0<=self.negative<len(self.schema) or
                self.schema[self.negative].kind!='int' or self.negative==self.positive):
            raise ValueError('negative term must reference a distinct numeric column')
        if len({i for i,m in self.filters})!=len(self.filters) or any(
            not 0<=i<len(self.schema) or self.schema[i].kind!='bool' or m not in (1,2,3)
            for i,m in self.filters):
            raise ValueError('invalid typed filter')

    @property
    def key(self)->str:
        payload=([(c.name,c.kind) for c in self.schema],self.positive,self.negative,self.filters)
        return 'sql:'+hashlib.sha256(json.dumps(payload).encode()).hexdigest()

    def accepts(self,snapshot:Snapshot)->bool:
        return snapshot.columns==self.schema

    def __call__(self,snapshot:Snapshot)->int:
        if not self.accepts(snapshot):
            raise ValueError('schema/dependency guard failed; never reuse silently')
        total=0
        for row in snapshot.rows:
            if all((row[i]==m-1 if m in (1,2) else (row[i] or 0)==0)
                   for i,m in self.filters):
                total+=(row[self.positive] or 0)-(row[self.negative] or 0 if self.negative is not None else 0)
        return total

    def sql(self)->str:
        def name(i:int)->str:
            return '"'+self.schema[i].name+'"'
        expr='COALESCE('+name(self.positive)+',0)'
        if self.negative is not None:
            expr+='-COALESCE('+name(self.negative)+',0)'
        where=[]
        for i,m in self.filters:
            where.append(name(i)+'='+str(m-1) if m in (1,2) else 'COALESCE('+name(i)+',0)=0')
        return 'SELECT COALESCE(SUM('+expr+'),0) FROM "records"'+(
            ' WHERE '+' AND '.join(where) if where else '')

    def as_rule(self)->Rule:
        return Rule(self.key,self)

def schema_grammar(columns:tuple[Column,...])->tuple[tuple[Rule,...],tuple[Rule,...]]:
    numeric=[i for i,c in enumerate(columns) if c.kind=='int']
    flags=[i for i,c in enumerate(columns) if c.kind=='bool']
    if not numeric or len(numeric)>8 or len(flags)>3:
        raise ValueError('unsupported schema size; use the general fallback')
    tiers=[[],[]]
    for pos in numeric:
        for neg in [None]+[j for j in numeric if j!=pos]:
            for modes in product(range(4),repeat=len(flags)):
                fs=tuple((i,m) for i,m in zip(flags,modes) if m)
                plan=SumPlan(columns,pos,neg,fs)
                tiers[int(neg is not None)].append(plan.as_rule())
    # A one-numeric-column schema has no difference tier.
    return tuple(tuple(t) for t in tiers if t)

def sqlite_evaluate(plan:SumPlan,snapshot:Snapshot)->int:
    """Independent backend for parity testing; no external database or credentials."""
    if not plan.accepts(snapshot):
        raise ValueError('schema mismatch')
    with sqlite3.connect(':memory:') as db:
        schema=','.join('"'+c.name+'" INTEGER' for c in snapshot.columns)
        db.execute('CREATE TABLE "records" ('+schema+')')
        db.executemany('INSERT INTO "records" VALUES ('+','.join('?' for c in snapshot.columns)+')',snapshot.rows)
        db.execute('PRAGMA query_only=ON')
        return int(db.execute(plan.sql()).fetchone()[0])

def parse_plan(text:str,columns:tuple[Column,...])->SumPlan:
    """Parse one constrained model proposal. No SQL/code evaluation or key repair."""
    if not isinstance(text,str) or len(text)>16384:
        raise ValueError('proposal must be bounded JSON text')
    obj=json.loads(text)
    if not isinstance(obj,dict) or set(obj)!={'positive','negative','filters'}:
        raise ValueError('exact proposal fields required')
    names={c.name:i for i,c in enumerate(columns)}
    if not isinstance(obj['positive'],str) or (obj['negative'] is not None and not isinstance(obj['negative'],str)):
        raise ValueError('column identifiers must be strings')
    if obj['positive'] not in names or (obj['negative'] is not None and obj['negative'] not in names):
        raise ValueError('unknown public column')
    filters=obj['filters']
    if not isinstance(filters,list) or len(filters)>len(columns):
        raise ValueError('invalid filters')
    modes={'equals_zero':1,'equals_one':2,'null_or_zero':3}
    parsed=[]
    for item in filters:
        if not isinstance(item,dict) or set(item)!={'column','mode'} or not isinstance(item['column'],str) or not isinstance(item['mode'],str) or item['column'] not in names or item['mode'] not in modes:
            raise ValueError('invalid typed filter proposal')
        parsed.append((names[item['column']],modes[item['mode']]))
    return SumPlan(columns,names[obj['positive']],None if obj['negative'] is None else names[obj['negative']],tuple(parsed))

def cube_evaluate(plans:tuple[SumPlan,...],snapshot:Snapshot)->tuple[int,...]:
    """Factor shared work using an exact 3^f by c nullable-Boolean aggregate cube.

    Every row belongs to one bucket (NULL,0,1 per flag). Filtered sums are a
    linear map of this cube; sum/difference plans are then column combinations.
    Worst-case integer magnitudes are bounded by Snapshot's input contract.
    No data-dependent summary is cached across snapshots.
    """
    import numpy as np
    if any(not p.accepts(snapshot) for p in plans):
        raise ValueError('schema guard mismatch')
    flags=[i for i,c in enumerate(snapshot.columns) if c.kind=='bool']
    numeric=[i for i,c in enumerate(snapshot.columns) if c.kind=='int']
    if len(flags)>3 or len(numeric)>8:
        raise ValueError('cube reference supports at most three flags and eight numeric fields')
    cube=np.zeros((3**len(flags),len(numeric)),dtype=np.int64)
    flag_position={i:j for j,i in enumerate(flags)}
    num_position={i:j for j,i in enumerate(numeric)}
    for row in snapshot.rows:
        code=sum((0 if row[i] is None else row[i]+1)*3**j for j,i in enumerate(flags))
        for j,i in enumerate(numeric):cube[code,j]+=row[i] or 0
    filtered={}
    result=[]
    for p in plans:
        if p.filters not in filtered:
            ids=[]
            for code in range(len(cube)):
                accepted=True
                for i,m in p.filters:
                    symbol=(code//(3**flag_position[i]))%3
                    accepted&=(symbol==m if m in (1,2) else symbol in (0,1))
                if accepted:ids.append(code)
            filtered[p.filters]=cube[ids].sum(axis=0)
        v=filtered[p.filters]
        result.append(int(v[num_position[p.positive]])-(int(v[num_position[p.negative]]) if p.negative is not None else 0))
    return tuple(result)
