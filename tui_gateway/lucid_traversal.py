"""Help-scoped LUCID choices; no execution or model-owned authority."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Callable

from hermes_gestalt import canonical_stream, semantic_action
from hermes_penguin import penguin_max_tokens
from tui_gateway import penguin_funnel
from agent.generated.ae_glyphs import SIGNAL_GREEN, SIGNAL_PENDING, DELIMITER_SEGMENT

MAX_CHOICES = 128
MAX_PROMPT_BYTES = 16_384
MAX_STEPS = 16
MAX_ATTEMPTS = 2


def cell(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def choice_labels(choices: dict[str, str]) -> dict[str, str]:
    labels = {}
    for value in choices:
        label = value.upper()
        if label == SIGNAL_PENDING or label in labels:
            raise ValueError("lucid-help-choice-collision")
        labels[label] = value
    return labels


def choice_instruction(stage: str, choices: dict[str, str], decisions: dict) -> str:
    choice_labels(choices)
    return penguin_funnel.project(stage, decisions, choices=choices)["prompt"]


def literal_instruction(key: str, schema: dict, decisions: dict) -> str:
    return penguin_funnel.project("lucid-argument:" + key, decisions, schema=schema)["prompt"]


def digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def prompt_hash(prompt: str) -> str:
    return "sha256:" + hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def selection_retry(prompt: str) -> str:
    return prompt + "\n\n**FEEDBACK** · **RULE**\nINVALID LABEL · RETURN ONE DECLARED LABEL OR " + SIGNAL_PENDING


def noun_choices(targets: dict) -> dict[str, str]:
    return {name: target.get("meaning", name) for name, target in targets.items()}


def optional_choices(target: dict, selected: list[str]) -> dict[str, str]:
    return {"omit": "NO FURTHER REQUESTED OPTIONAL FIELDS",
        **{key: key for key in target["optional"] if key not in selected}}


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
        if SIGNAL_PENDING in choices:
            raise ValueError("lucid-help-choice-collision")
        labels = choice_labels(choices)
        prompt = choice_instruction(stage, choices, self.decisions)
        if len(prompt.encode()) > MAX_PROMPT_BYTES:
            raise ValueError("lucid-help-prompt-bound")
        record = {"stage": stage, "help_source": source, "help_hash": digest(choices), "system_prompt": prompt,
            "system_prompt_hash": prompt_hash(prompt),
            "choices": dict(choices), "output_labels": labels, "resolved_before": deepcopy(self.decisions), "selection_source": "explicit" if pinned is not None else "penguin"}
        self.record(record)
        record["attempts"] = []
        for attempt in range(1 if pinned is not None else MAX_ATTEMPTS):
            if len(prompt.encode("utf-8")) > MAX_PROMPT_BYTES:
                record["validation"] = "prompt-bound"
                raise ValueError("lucid-help-prompt-bound")
            attempt_record = {"system_prompt": prompt, "system_prompt_hash": prompt_hash(prompt),
                "input": self.original, "max_tokens": penguin_max_tokens(self.original),
                "selection": None, "accepted": False, "inference_ran": pinned is None}
            record["attempts"].append(attempt_record)
            selected = pinned if pinned is not None else self.infer(self.original, prompt, stage, penguin_max_tokens(self.original)).strip()
            wire_value = selected if pinned is not None and selected in choices else labels.get(selected.upper()) if pinned is None else None
            attempt_record.update(selection=selected, accepted=wire_value is not None, wire_value=wire_value)
            record["selected"] = wire_value if wire_value is not None else selected
            if wire_value is not None:
                selected = wire_value
                break
            if selected == SIGNAL_PENDING:
                record["validation"] = "missing-or-ambiguous"
                raise ValueError("lucid-help-selection-unresolved:" + stage)
            if pinned is not None or attempt == MAX_ATTEMPTS - 1:
                record["validation"] = "refused"
                raise ValueError("lucid-help-selection-invalid:" + stage)
            prompt = selection_retry(prompt)
        record["validation"] = "accepted"
        return selected

    def targets(self, verb: str) -> dict[str, dict]:
        schema = self.vocabulary["verbs"][verb]["args"]
        if verb == "show":
            views = schema.get("x-attention-views", {}).get("views", {})
            return {name: {"selector": "view", "meaning": SHOW_NOUN_PROMPTS.get(name, (name.replace("-", " "), ""))[0], "required": contract.get("required", []),
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
                    "meaning": target.get("materializer", target["id"]).replace("-", " "),
                    "required": ["path"] + (["value"] if verb == "set" else []),
                    "optional": [key for key in target.get("arguments", {}).get("allowed", []) if key != "path"],
                    "contract": target}
            return projected
        raise ValueError("lucid-noun-help-unavailable:" + verb)

    def noun(self, verb: str, pinned: str | None = None) -> tuple[str, dict]:
        targets = self.targets(verb)
        choices = noun_choices(targets)
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
        if not supplied and any(self.records[index].get("selection_source") in {"penguin", "classifier"} for index in range(len(self.records))):
            selected_optional = []
            while any(key not in selected_optional for key in target["optional"]):
                selected = self.choose("lucid-optional", optional_choices(target, selected_optional),
                    f"envelope/LUCID.json#/verbs/{verb}/args")
                if selected == "omit":
                    break
                requested.append(selected)
                self.decisions.setdefault("optional_arguments", []).append(selected)
                selected_optional.append(selected)
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
                prompt = literal_instruction(key, schema, self.decisions)
                if len(prompt.encode()) > MAX_PROMPT_BYTES:
                    raise ValueError("lucid-help-prompt-bound")
                record = self.record({"stage": "lucid-argument:" + key, "help_source": f"envelope/LUCID.json#/verbs/{verb}/args/properties/{key}",
                    "help_hash": digest(schema), "system_prompt": prompt, "system_prompt_hash": prompt_hash(prompt),
                    "input": self.original, "max_tokens": penguin_max_tokens(self.original),
                    "selection_source": "penguin", "selected": None,
                    "resolved_before": deepcopy(self.decisions)})
                selected = self.infer(self.original, prompt, record["stage"], penguin_max_tokens(self.original)).strip()
                record["selected"] = selected
                try:
                    value = json.loads(selected)
                except (ValueError, TypeError):
                    record["validation"] = "refused"
                    raise ValueError("lucid-argument-needs-clarification:" + key) from None
                if not isinstance(value, str) or not value or (value not in self.original and cell(value) not in self.original):
                    record["validation"] = "refused"
                    raise ValueError("lucid-argument-needs-clarification:" + key)
                result[key] = value
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

    def run(self, root, operation: dict | None = None, *, classified_verb: str) -> dict:
        if classified_verb not in self.vocabulary["verbs"]:
            raise ValueError("lucid-verb-not-declared")
        if operation and operation["verb"] != classified_verb:
            raise ValueError("classifier-verb-mismatch")
        verb = classified_verb
        self.decisions["verb"] = verb
        self.decisions["verb_glyph"] = self.vocabulary["verbs"][verb]["glyph"]
        self.record({"stage": "lucid-verb", "help_source": "envelope/LUCID.json#/verbs",
            "help_hash": digest(self.vocabulary["verbs"]), "selected": verb,
            "selection_source": "explicit" if operation else "classifier",
            "classification_selection": self.vocabulary["verbs"][verb]["glyph"], "inference_ran": False,
            "attempts": [], "validation": "accepted-classifier-verb"})
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
            "result": traversal.run(root, operation, classified_verb=operation["verb"])})
    return results


def receipt_selection_prompts(vocabulary: dict) -> list[dict]:
    def no_inference(*args):
        raise ValueError("generation-must-not-infer")

    traversal = Traversal("", vocabulary, no_inference)
    records = []
    inputs = {"show": "Open https://example.com/ with scope this.",
        "get": "Retrieve runtime logs.", "set": "Change the radio settings."}

    def capture(stage, prompt, decisions, source, contract, original):
        if len(prompt.encode("utf-8")) > MAX_PROMPT_BYTES:
            raise ValueError("lucid-help-prompt-bound")
        records.append({"stage": stage, "system_prompt": prompt, "system_prompt_hash": prompt_hash(prompt),
            "resolved_before": deepcopy(decisions), "help_source": source, "help_hash": digest(contract),
            "input": original, "input_hash": prompt_hash(original),
            "input_source": "unchanged original request for this generation-only case",
            "inference_ran": False, "execution_ran": False})

    for verb in ("show", "get", "set"):
        targets = traversal.targets(verb)
        source = f"envelope/LUCID.json#/verbs/{verb}/args/x-attention-views/views" if verb == "show" else f"envelope/LUCID.json#/{verb}_registry/targets"
        decisions = {"verb": verb, "verb_glyph": vocabulary["verbs"][verb]["glyph"]}
        choices = noun_choices(targets)
        capture("lucid-noun", choice_instruction("lucid-noun", choices, decisions), decisions,
            source, choices, inputs[verb])
    targets = traversal.targets("show")
    decisions = {"verb": "show", "verb_glyph": vocabulary["verbs"]["show"]["glyph"], "noun": "url"}
    choices = optional_choices(targets["url"], [])
    source = "envelope/LUCID.json#/verbs/show/args"
    prompt = choice_instruction("lucid-optional", choices, decisions)
    capture("lucid-optional", prompt, decisions, source, choices, inputs["show"])
    capture("lucid-optional:retry", selection_retry(prompt), decisions, source, choices, inputs["show"])
    properties = vocabulary["verbs"]["show"]["args"]["properties"]
    decisions["optional_arguments"] = ["scope"]
    capture("lucid-argument:url", literal_instruction("url", properties["url"], decisions), decisions,
        source + "/properties/url", properties["url"], inputs["show"])
    capture("lucid-argument:scope", literal_instruction("scope", properties["scope"], decisions), decisions,
        source + "/properties/scope", properties["scope"], inputs["show"])
    for noun, target in targets.items():
        for key in target["required"] + target["optional"]:
            options = properties.get(key, {}).get("enum")
            if key == target["selector"] or not options or not all(isinstance(value, str) for value in options):
                continue
            original = "Open " + options[0] + "."
            decisions = {"verb": "show", "verb_glyph": vocabulary["verbs"]["show"]["glyph"]}
            capture("lucid-noun", choice_instruction("lucid-noun", noun_choices(targets), decisions), decisions,
                "envelope/LUCID.json#/verbs/show/args/x-attention-views/views", noun_choices(targets), original)
            decisions["noun"] = noun
            choices = {value: key for value in options}
            stage = "lucid-argument:" + key
            capture(stage, choice_instruction(stage, choices, decisions), decisions,
                source + "/properties/" + key, choices, original)
            return records
    return records