from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True, order=True)
class Scope:
    """A public environment identifier and externally observed version, NOT a latent task ID."""
    name: str
    version: str = "v1"

    def __post_init__(self) -> None:
        if type(self.name) is not str or type(self.version) is not str:
            raise TypeError("public scope identifiers must be strings")
        if not self.name or not self.version:
            raise ValueError("scope name and public version must be nonempty")

@dataclass(frozen=True)
class Feedback:
    episode: int
    scope: Scope
    x: int
    action: int
    success: bool

    def __post_init__(self) -> None:
        if type(self.episode) is not int or self.episode < 0:
            raise ValueError("episode must be a nonnegative integer")
        if type(self.x) is not int or type(self.action) is not int:
            raise TypeError("the finite reference uses integer inputs and actions")
        if type(self.success) is not bool:
            raise TypeError("success must come from the trusted environment as a bool")

@dataclass(frozen=True)
class Decision:
    action: int
    certified: bool
    basis: str
    live_hypotheses: int
