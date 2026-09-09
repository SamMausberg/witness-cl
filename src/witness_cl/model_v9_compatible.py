"""Portable schema encoding with all semantic size checks retained by the host."""
from copy import deepcopy
from dataclasses import replace
from .model_v9 import LocalInferenceV9

WIRE_SCHEMA_POLICY = 'host_checks_large_string_bounds_v1'

def portable_schema(schema):
    """Remove only large string bounds that explode the native grammar parser.

    Shape, field names, scalar types, array counts and small bounds are kept.
    No response or SQL is repaired; memory admission still validates size.
    """
    if isinstance(schema, dict):
        return {k: portable_schema(v) for k, v in schema.items()
                if not (k == 'maxLength' and type(v) is int and v > 2000)}
    if isinstance(schema, list):
        return [portable_schema(v) for v in schema]
    return deepcopy(schema)

class LocalInferenceV9Compatible(LocalInferenceV9):
    def complete(self, messages, budget, *, phase, records, output_tokens=None, response_schema=None):
        if self.response_mode != 'schema':
            raise ValueError('portable schema transport requires schema mode')
        start = len(records)
        host_schema = deepcopy(response_schema)
        original_decoding = self.decoding
        if phase.endswith(':reflection'):
            self.decoding = replace(original_decoding, thinking=False)
        try:
            return super().complete(messages, budget, phase=phase, records=records,
                output_tokens=output_tokens, response_schema=portable_schema(host_schema))
        finally:
            self.decoding = original_decoding
            for record in records[start:]:
                record['wire_schema_policy'] = WIRE_SCHEMA_POLICY
                record['host_response_schema'] = deepcopy(host_schema)
                record['reflection_thinking'] = False
