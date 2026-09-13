"""Testbed access to Butler's canonical prompt projection; no corpus filtering."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "butler/tools/penguin_funnel.py"
_spec = importlib.util.spec_from_file_location("butler_penguin_funnel", SOURCE)
if _spec is None or _spec.loader is None:
    raise ImportError("Butler funnel projector unavailable")
owner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(owner)


def project(stage, decisions=None, choices=None, schema=None):
    result = owner.load_projection(ROOT, stage, decisions)
    if choices is not None and result["choices"] != choices:
        raise ValueError("funnel-choice-contract-drift")
    if schema is not None and result["argument_schema"] != schema:
        raise ValueError("funnel-argument-contract-drift")
    return result


def receipt(projection):
    return {key: projection[key] for key in ("artifact_hash", "corpus_hash", "case_ids", "context", "prompt_hash")}


def corpus():
    return owner.strict_json(owner.read(ROOT, owner.CORPUS))