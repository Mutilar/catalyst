"""Help-scoped LUCID choices; no execution or model-owned authority."""

from __future__ import annotations

import hashlib
import json
import shlex
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Callable

from hermes_gestalt import canonical_stream, semantic_action
from agent.generated.ae_glyphs import SIGNAL_GREEN

MAX_CHOICES = 128
MAX_PROMPT_BYTES = 16_384
MAX_STEPS = 16
MAX_ATTEMPTS = 2


def cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def decision_table(decisions: dict) -> str:
    rows = ["| Resolved | Value |", "|---|---|"]
    for key, glyph in (("verb", "⚡"), ("noun", "🎯")):
        if key in decisions:
            rows.append(f"| {glyph} | {cell(decisions[key])} |")
    for key in decisions.get("optional_arguments", []):
        rows.append(f"| ⚙️ | {cell(key)} |")
    return "\n".join(rows)


def digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@dataclass
class Traversal:
    original: str
    vocabulary: dict
    infer: Callable[[str, str, str, int], str]
    records: list[dict] = field(default_factory=list)
    decisions: dict = field(default_factory=dict)

    def record(self, value: dict) -> dict:
        if len(self.records) >= MAX_STEPS:
            raise ValueError("lucid-traversal-step-bound")
        self.records.append(value)
        return value

    def choose(self, stage: str, choices: dict[str, str], source: str, pinned: str | None = None) -> str:
        if not choices or len(choices) > MAX_CHOICES or len(self.records) >= MAX_STEPS:
            raise ValueError("lucid-help-choice-bound")
        prompt = "Select one exact choice for the original request. Return only the choice.\n\n"
        prompt += "| Choice | Meaning |\n|---|---|\n"
        prompt += "\n".join(f"| {cell(key)} | {cell(value)} |" for key, value in choices.items())
        prompt += "\n\n" + decision_table(self.decisions)
        if len(prompt.encode()) > MAX_PROMPT_BYTES:
            raise ValueError("lucid-help-prompt-bound")
        record = {"stage": stage, "help_source": source, "help_hash": digest(choices), "system_prompt": prompt,
            "choices": dict(choices), "resolved_before": deepcopy(self.decisions), "selection_source": "explicit" if pinned is not None else "penguin"}
        self.record(record)
        record["attempts"] = []
        for attempt in range(1 if pinned is not None else MAX_ATTEMPTS):
            selected = pinned if pinned is not None else self.infer(self.original, prompt, stage, 64).strip()
            record["attempts"].append({"selection": selected, "accepted": selected in choices})
            record["selected"] = selected
            if selected in choices:
                break
            if pinned is not None or attempt == MAX_ATTEMPTS - 1:
                record["validation"] = "refused"
                raise ValueError("lucid-help-selection-invalid:" + stage)
            prompt += "\nPrevious selection was not a declared choice. Select exactly one listed choice."
        record["validation"] = "accepted"
        return selected

    def verb(self, pinned: str | None = None) -> str:
        if pinned is not None and pinned not in self.vocabulary["verbs"]:
            raise ValueError("lucid-verb-not-declared")
        choices = {value["glyph"]: name.upper() for name, value in self.vocabulary["verbs"].items()}
        selected = self.choose("lucid-verb", choices, "envelope/LUCID.json#/verbs",
            self.vocabulary["verbs"].get(pinned, {}).get("glyph") if pinned else None)
        verb = next(name for name, value in self.vocabulary["verbs"].items() if value["glyph"] == selected)
        self.decisions["verb"] = verb
        return verb

    def targets(self, verb: str) -> dict[str, dict]:
        schema = self.vocabulary["verbs"][verb]["args"]
        if verb == "show":
            views = schema.get("x-attention-views", {}).get("views", {})
            return {name: {"selector": "view", "required": contract.get("required", []),
                "optional": contract.get("optional", [])} for name, contract in views.items()
                if not any("id" in key or "hash" in key for key in contract.get("required", []))}
        if verb in {"get", "set"}:
            targets = self.vocabulary[verb + "_registry"]["targets"]
            projected = {}
            for target in targets:
                selector = target.get("selector" if verb == "get" else "path", {})
                if selector.get("kind") != "exact" or any("hash" in key for key in target.get("preconditions", [])):
                    continue
                projected[selector["value"]] = {"selector": "path",
                    "required": ["path"] + (["value"] if verb == "set" else []),
                    "optional": [key for key in target.get("arguments", {}).get("allowed", []) if key != "path"],
                    "contract": target}
            return projected
        raise ValueError("lucid-noun-help-unavailable:" + verb)

    def noun(self, verb: str, pinned: str | None = None) -> tuple[str, dict]:
        targets = self.targets(verb)
        choices = {name: " / ".join(targets[name]["required"]) for name in targets}
        source = f"envelope/LUCID.json#/verbs/{verb}/args/x-attention-views/views" if verb == "show" else f"envelope/LUCID.json#/{verb}_registry/targets"
        selected = self.choose("lucid-noun", choices, source, pinned)
        self.records[-1]["contract_hash"] = digest(targets[selected])
        self.decisions["noun"] = selected
        return selected, targets[selected]

    def arguments(self, verb: str, noun: str, target: dict, supplied: dict) -> dict:
        properties = self.vocabulary["verbs"][verb]["args"]["properties"]
        result = {target["selector"]: noun}
        allowed = set(target["required"] + target["optional"])
        for key, value in supplied.items():
            if key not in allowed:
                raise ValueError("lucid-target-argument-not-declared")
            result[key] = value
        requested = list(target["required"])
        if not supplied and any(self.records[index].get("selection_source") == "penguin" for index in range(len(self.records))):
            optional = {key: key for key in target["optional"]}
            while optional:
                selected = self.choose("lucid-optional", {"omit": "No further explicitly requested optional arguments", **optional},
                    f"envelope/LUCID.json#/verbs/{verb}/args")
                if selected == "omit":
                    break
                requested.append(selected)
                self.decisions.setdefault("optional_arguments", []).append(selected)
                del optional[selected]
        for key in requested:
            if key in result:
                continue
            schema = properties.get(key, {})
            options = schema.get("enum")
            if options and all(isinstance(value, str) for value in options):
                result[key] = self.choose("lucid-argument:" + key, {value: key for value in options},
                    f"envelope/LUCID.json#/verbs/{verb}/args/properties/{key}")
            else:
                if schema.get("type") != "string":
                    raise ValueError("lucid-required-argument-missing:" + key)
                prompt = "Return the exact requested literal value, quoted as a string, or ⏳ if missing.\n\n"
                prompt += f"| Argument | Type | Maximum length |\n|---|---|---|\n| {key} | string | {schema.get('maxLength', 16384)} |"
                prompt += "\n\n" + decision_table(self.decisions)
                if len(prompt.encode()) > MAX_PROMPT_BYTES:
                    raise ValueError("lucid-help-prompt-bound")
                record = self.record({"stage": "lucid-argument:" + key, "help_source": f"envelope/LUCID.json#/verbs/{verb}/args/properties/{key}",
                    "help_hash": digest(schema), "system_prompt": prompt, "resolved_before": deepcopy(self.decisions)})
                selected = self.infer(self.original, prompt, record["stage"], 512).strip()
                record["selected"] = selected
                try:
                    values = shlex.split(selected)
                except ValueError:
                    record["validation"] = "refused"
                    raise ValueError("lucid-argument-needs-clarification:" + key) from None
                if len(values) != 1 or not values[0] or selected == "⏳" or values[0] not in self.original:
                    record["validation"] = "refused"
                    raise ValueError("lucid-argument-needs-clarification:" + key)
                result[key] = values[0]
                record["validation"] = "source-literal-present"
        for key, value in result.items():
            schema = properties.get(key, {})
            if "enum" in schema and value not in schema["enum"]:
                raise ValueError("lucid-argument-value-invalid:" + key)
            kind = schema.get("type")
            types = kind if isinstance(kind, list) else [kind]
            actual = "null" if value is None else "boolean" if isinstance(value, bool) else "string" if isinstance(value, str) else "integer" if isinstance(value, int) else "number" if isinstance(value, float) else "object" if isinstance(value, dict) else "array"
            if kind and actual not in types and not (actual == "integer" and "number" in types):
                raise ValueError("lucid-argument-type-invalid:" + key)
            if isinstance(value, str) and len(value) > schema.get("maxLength", 16_384):
                raise ValueError("lucid-argument-bound:" + key)
        if verb == "get":
            query_contract = target.get("contract", {}).get("query")
            if "query" in result and query_contract:
                query = result["query"]
                if not isinstance(query, dict) or set(query) - set(query_contract["allowed"]) or set(query_contract.get("required", [])) - set(query):
                    raise ValueError("lucid-query-contract-mismatch")
            elif query_contract and query_contract.get("required"):
                raise ValueError("lucid-required-query-missing")
        self.decisions["arguments"] = result
        self.record({"stage": "lucid-arguments", "help_source": f"envelope/LUCID.json#/verbs/{verb}/args",
            "help_hash": digest({key: properties.get(key) for key in allowed}),
            "required": target["required"], "optional": target["optional"], "selected": result,
            "validation": "accepted-structural-only; Butler preflight remains required"})
        return result

    def run(self, root, operation: dict | None = None) -> dict:
        verb = self.verb(operation["verb"] if operation else None)
        if verb == "morph":
            return {"semantic_required": True, "steps": self.records}
        argv = operation["argv"] if operation else []
        supplied = {}
        pinned = None
        if argv[:1] == ["--args"]:
            if len(argv) != 2:
                raise ValueError("lucid-explicit-arguments-unresolved")
            supplied = json.loads(argv[1])
            if not isinstance(supplied, dict):
                raise ValueError("lucid-arguments-object-required")
            selector = next(iter(self.targets(verb).values()), {}).get("selector")
            pinned = supplied.get(selector)
        elif argv:
            pinned = argv[0].lower()
            target = self.targets(verb).get(pinned)
            if target is None:
                raise ValueError("lucid-noun-not-declared")
            remaining = [key for key in target["required"] if key != target["selector"]]
            if len(argv) - 1 > len(remaining):
                raise ValueError("lucid-explicit-arguments-unresolved")
            supplied = dict(zip(remaining, argv[1:]))
        noun, target = self.noun(verb, pinned)
        arguments = self.arguments(verb, noun, target, supplied)
        selectors = json.loads((root / "envelope/GESTALT.json").read_text())["segments"]["operationSelectors"][verb]
        projection_arguments = dict(arguments)
        if any(selector.get("nounFrom") == "key" and selector["path"] == noun for selector in selectors):
            if projection_arguments.get(target["selector"]) == noun and noun != target["selector"]:
                del projection_arguments[target["selector"]]
        action = semantic_action(root, verb, projection_arguments, verb.capitalize() + " " + noun)
        rendered = canonical_stream(root, SIGNAL_GREEN, actions=(action,))
        action_text = rendered[rendered.index("➡️"):]
        return {"operation": operation or {"channel": "lucid", "verb": verb, "argv": ["--args", json.dumps(arguments, separators=(",", ":"))]},
            "resolved_arguments": arguments,
            "gestalt": action_text, "steps": self.records, "vocabulary_hash": digest(self.vocabulary)}


def receipt_walkthroughs(root, vocabulary: dict) -> list[dict]:
    examples = [
        ("SHOW PULSE", {"channel": "lucid", "verb": "show", "argv": ["PULSE"]}),
        ('SHOW URL "https://example.com/"', {"channel": "lucid", "verb": "show", "argv": ["URL", "https://example.com/"]}),
        ('SHOW APP "macos-shell"', {"channel": "lucid", "verb": "show", "argv": ["APP", "macos-shell"]}),
        ("GET role", {"channel": "lucid", "verb": "get", "argv": ["role"]}),
        ("MORPH", {"channel": "lucid", "verb": "morph", "argv": []}),
    ]

    def no_inference(*args):
        raise ValueError("generation-must-not-infer")

    results = []
    for original, operation in examples:
        traversal = Traversal(original, vocabulary, no_inference)
        results.append({"input": original, "inference_ran": False, "execution_ran": False,
            "result": traversal.run(root, operation)})
    return results