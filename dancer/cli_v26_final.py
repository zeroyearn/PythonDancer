"""Final CLI layer for PythonDancer 2.6 continuous Motion Intent controls."""
from __future__ import annotations

from dataclasses import replace

from . import cli_v26
from .intent import INTENT_FIELDS, infer_motion_intent


def cmd(args):
    amount = float(getattr(args, "intent_override_amount", 0.0))
    if not 0.0 <= amount <= 1.0:
        print("--intent_override_amount must be within 0..1.")
        return 2
    manual = {}
    for field in INTENT_FIELDS:
        value = float(getattr(args, f"intent_{field}", .5))
        if not 0.0 <= value <= 1.0:
            print(f"--intent_{field} must be within 0..1.")
            return 2
        manual[field] = value

    base_multi = cli_v26._multi_config
    base_metadata = cli_v26._choreography_metadata

    def multi_config(inner_args, motion, profile=None):
        config = base_multi(inner_args, motion, profile)
        independent = replace(
            config.independent,
            intent_override=manual,
            intent_override_amount=amount,
        )
        return replace(config, independent=independent)

    def choreography_metadata(config, analysis, data):
        payload = base_metadata(config, analysis, data)
        payload["independent_axes"]["intent_override_amount"] = float(config.independent.intent_override_amount)
        payload["independent_axes"]["intent_override"] = dict(config.independent.intent_override)
        if getattr(args, "show_intent", False):
            inferred = infer_motion_intent(data, analysis).global_intent.to_dict()
            print("Motion Intent:")
            for field in INTENT_FIELDS:
                effective = (1.0 - amount) * inferred[field] + amount * manual[field]
                print(f"  {field:<18} inferred={inferred[field]:.2f}  effective={effective:.2f}")
        return payload

    cli_v26._multi_config = multi_config
    cli_v26._choreography_metadata = choreography_metadata
    try:
        return cli_v26.cmd(args)
    finally:
        cli_v26._multi_config = base_multi
        cli_v26._choreography_metadata = base_metadata
