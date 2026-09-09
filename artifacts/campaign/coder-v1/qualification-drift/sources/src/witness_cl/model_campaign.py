"""Campaign decoding on the existing measured, loopback-only transport.

The inherited request builder uses the complete decoding dataclass for both
preflight and generation, so the repetition penalty is neither a server default
nor a setting omitted from the generation receipt. Frozen clients are unchanged.
"""

from copy import deepcopy
from dataclasses import dataclass
import math

from .model_v9 import DecodingV9
from .model_v9_compatible import LocalInferenceV9Compatible


@dataclass(frozen=True)
class DecodingCampaign(DecodingV9):
    presence_penalty: float = 0.0
    repeat_penalty: float = 1.05
    repeat_last_n: int = 65536
    frequency_penalty: float = 0.0
    thinking: bool = False

    def __post_init__(self):
        super().__post_init__()
        if (
            type(self.repeat_penalty) not in (int, float)
            or not math.isfinite(self.repeat_penalty)
            or not 0 < self.repeat_penalty <= 2
        ):
            raise ValueError("repeat_penalty must be finite and in (0, 2]")
        if self.thinking:
            raise ValueError("the campaign instruct model uses nonthinking decoding")
        if type(self.repeat_last_n) is not int or self.repeat_last_n < 0:
            raise ValueError("repeat_last_n must be nonnegative on the pinned server API")
        if (
            type(self.frequency_penalty) not in (int, float)
            or not math.isfinite(self.frequency_penalty)
            or not -2 <= self.frequency_penalty <= 2
        ):
            raise ValueError("frequency_penalty must be finite and in [-2, 2]")


class LocalInferenceCampaign(LocalInferenceV9Compatible):
    def __init__(self, *, decoding=None, **connection):
        if decoding is None:
            decoding = DecodingCampaign()
        if not isinstance(decoding, DecodingCampaign):
            raise ValueError("campaign client requires DecodingCampaign")
        super().__init__(decoding=decoding, **connection)

    def snapshot_config(self):
        """Public inference configuration; credentials are deliberately absent."""
        return {
            "endpoint": self.endpoint,
            "model": self.model,
            "context_tokens": self.context_tokens,
            "max_output": self.max_output,
            "timeout": self.timeout,
            "response_mode": self.response_mode,
            "decoding": self.decoding.to_dict(),
            "repeat_penalty": self.decoding.repeat_penalty,
            "wire_schema_policy": "host_checks_large_string_bounds_v1",
        }


def build_client(config, key_file, *, max_output=4096, timeout=180.0):
    """Build the campaign transport from the frozen runtime config."""
    cfg = deepcopy(config)
    server = cfg["server"]
    return LocalInferenceCampaign(
        endpoint=f"http://{server['host']}:{server['port']}",
        model=cfg["model"]["alias"],
        key_file=key_file,
        context_tokens=server["context_tokens"],
        max_output=max_output,
        timeout=timeout,
        response_mode="schema",
        decoding=DecodingCampaign(**cfg["decoding"]),
    )
