"""Testbed access to Butler's canonical prompt projection; no corpus filtering."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CORPUS = "butler/canon/penguin/few-shots.json"
ARTIFACT = "butler/json/penguin-funnel.json"
SOURCES = (CORPUS, "butler/canon/penguin/classification.md",
    "butler/canon/penguin/semantic.md", "butler/src/generate_penguin_funnel.rs",
    "envelope/LUCID.json", "envelope/GESTALT.json")
MAX_BYTES = 4 * 1024 * 1024


def digest(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


def strict_json(data):
    def unique(entries):
        result = {}
        for key, value in entries:
            if key in result:
                raise ValueError("funnel-duplicate-key")
            result[key] = value
        return result

    def invalid_constant(_value):
        raise ValueError("funnel-json-invalid")

    return json.loads(data, object_pairs_hook=unique, parse_constant=invalid_constant)


def read(root, relative):
    path = Path(relative)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise ValueError("funnel-source-path")
    current = Path(root).resolve()
    for part in path.parts:
        current /= part
        if current.is_symlink():
            raise ValueError("funnel-source-path")
    if not current.is_file():
        raise ValueError("funnel-source-unavailable")
    if current.stat().st_size > MAX_BYTES:
        raise ValueError("funnel-source-bound")
    with current.open("rb") as source:
        data = source.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("funnel-source-bound")
    return data


def load_artifact(root):
    data = read(root, ARTIFACT)
    artifact = strict_json(data)
    if (not isinstance(artifact, dict) or artifact.get("schema") != "penguin-funnel-projection/1"
        or artifact.get("owner") != "butler" or not isinstance(artifact.get("sources"), dict)
        or set(artifact["sources"]) != set(SOURCES) or artifact.get("inference_ran") is not False
        or artifact.get("expected_answers_are_observations") is not False):
        raise ValueError("funnel-artifact-invalid")
    for name, expected in artifact["sources"].items():
        if digest(read(root, name)) != expected:
            raise ValueError("funnel-projection-stale:" + name)
    if artifact.get("corpus_hash") != artifact["sources"][CORPUS]:
        raise ValueError("funnel-corpus-drift")
    return artifact, digest(data)


def load_projection(root, stage, decisions=None):
    artifact, artifact_hash = load_artifact(root)
    decisions = decisions or {}
    context = {"stage": stage, **{key: decisions[key] for key in ("verb", "noun", "optional_arguments") if key in decisions}}
    matches = [entry for entry in artifact["projections"] if entry.get("context") == context]
    if len(matches) != 1:
        raise ValueError("funnel-coverage-gap")
    entry = matches[0]
    prompt = entry.get("prompt")
    cases = entry.get("case_ids")
    retry = entry.get("retry_prompt")
    if (not isinstance(prompt, str) or not 0 < len(prompt.encode()) <= 16384
        or digest(prompt.encode()) != entry.get("prompt_hash")
        or not isinstance(cases, list) or not 0 < len(cases) <= 128
        or not all(isinstance(case, str) and case for case in cases) or len(set(cases)) != len(cases)
        or retry is not None and (not isinstance(retry, str) or len(retry.encode()) > 16384
            or digest(retry.encode()) != entry.get("retry_prompt_hash"))):
        raise ValueError("funnel-projection-invalid")
    return {**entry, "artifact_hash": artifact_hash, "corpus_hash": artifact["corpus_hash"]}


def targets(vocabulary, verb):
    artifact, _ = load_artifact(ROOT)
    if vocabulary != strict_json(read(ROOT, "envelope/LUCID.json")):
        raise ValueError("funnel-vocabulary-drift")
    selected = artifact.get("targets", {}).get(verb)
    if not isinstance(selected, dict):
        raise ValueError("funnel-unsupported-verb")
    return selected


def project(stage, decisions=None, choices=None, schema=None):
    result = load_projection(ROOT, stage, decisions)
    if choices is not None and result["choices"] != choices:
        raise ValueError("funnel-choice-contract-drift")
    if schema is not None and result["argument_schema"] != schema:
        raise ValueError("funnel-argument-contract-drift")
    return result


def receipt(projection):
    return {key: projection[key] for key in ("artifact_hash", "corpus_hash", "case_ids", "context", "prompt_hash")}


def corpus():
    return strict_json(read(ROOT, CORPUS))