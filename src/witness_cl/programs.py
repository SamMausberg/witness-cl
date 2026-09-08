from __future__ import annotations
from dataclasses import dataclass
import hashlib
import json
from typing import Protocol

class Program(Protocol):
    def __call__(self, x: int) -> int: ...
    @property
    def key(self) -> str: ...

@dataclass(frozen=True, order=True)
class AffineMod:
    """A total, side-effect-free DSL program. No eval, imports, or generated Python."""
    a: int
    b: int
    modulus: int

    def __post_init__(self) -> None:
        if any(type(v) is not int for v in (self.a, self.b, self.modulus)):
            raise TypeError("DSL parameters must be integers")
        if not 2 <= self.modulus <= 257:
            raise ValueError("modulus must be in [2,257]")
        if not 0 <= self.a < self.modulus or not 0 <= self.b < self.modulus:
            raise ValueError("coefficients must be canonical residues")

    def __call__(self, x: int) -> int:
        if type(x) is not int:
            raise TypeError("input must be an integer")
        return (self.a * x + self.b) % self.modulus

    @property
    def key(self) -> str:
        return f"affine:{self.modulus}:{self.a}:{self.b}"

    def to_json(self) -> dict:
        return {"op": "affine_mod", "a": self.a, "b": self.b, "modulus": self.modulus}

    @staticmethod
    def parse(value: dict) -> "AffineMod":
        if type(value) is not dict or set(value) != {"op", "a", "b", "modulus"}:
            raise ValueError("unknown or missing DSL fields")
        if value["op"] != "affine_mod":
            raise ValueError("unsupported operation")
        return AffineMod(value["a"], value["b"], value["modulus"])


def affine_class(modulus: int) -> tuple[AffineMod, ...]:
    # Construction validates even when the proposed modulus is invalid.
    AffineMod(0, 0, modulus)
    return tuple(AffineMod(a, b, modulus) for a in range(modulus) for b in range(modulus))


def space_digest(programs: tuple[Program, ...]) -> str:
    data = json.dumps([p.key for p in programs], separators=(",", ":")).encode()
    return hashlib.sha256(data).hexdigest()
