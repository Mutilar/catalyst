"""Canonical GESTALT semantic stream projection from the AgentExperiments SOT."""

from __future__ import annotations

import json
from pathlib import Path

_MAX_CONTRACT_BYTES = 64 * 1024


def canonical_stream(
    root: Path,
    signal: str,
    verb: str | None = None,
    noun: str | None = None,
    argument: str | None = None,
    *,
    service: str | None = None,
    without_identity: bool = False,
    arguments: tuple[str, ...] = (),
    evidence: tuple[str, ...] = (),
    data: tuple[str, ...] = (),
    timing: tuple[str, ...] = (),
    continuations: tuple[str, ...] = (),
    intents: tuple[str, ...] = (),
    cli: tuple[str, ...] = (),
    actions: tuple[dict[str, object], ...] = (),
) -> str:
    path = root / "envelope/GESTALT.json"
    metadata = path.lstat()
    if path.is_symlink() or not path.is_file() or metadata.st_size > _MAX_CONTRACT_BYTES:
        raise ValueError("GESTALT contract is not a bounded regular file")
    contract = json.loads(path.read_text(encoding="utf-8"))
    header = contract.get("segments") if isinstance(contract, dict) else None
    glyphs = header.get("glyphs") if isinstance(header, dict) else None
    fields = header.get("order") if isinstance(header, dict) else None
    required = header.get("required") if isinstance(header, dict) else None
    optional = header.get("optional") if isinstance(header, dict) else None
    signals = header.get("signals") if isinstance(header, dict) else None
    separator = header.get("separator") if isinstance(header, dict) else None
    if (
        contract.get("schema") != "lucid-gestalt/1"
        or not isinstance(glyphs, dict)
        or not isinstance(fields, list)
        or required != ["signal"]
        or fields != ["signal", "service", "verb", "noun", "argument", "evidence", "datum", "timing", "action"]
        or optional != fields[1:]
        or not isinstance(signals, list)
        or signal not in signals
        or not isinstance(separator, str)
        or not separator
    ):
        raise ValueError("GESTALT segment contract is invalid")
    glyph_values = [glyphs.get(field) for field in fields[1:]]
    if not all(isinstance(field, str) and field for field in glyph_values):
        raise ValueError("GESTALT segment glyphs are invalid")
    default_service, verb_glyph, noun_glyph, argument_glyph, evidence_glyph, datum_glyph, timing_glyph, action_glyph = glyph_values
    if without_identity and service is not None:
        raise ValueError("GESTALT service conflicts with without_identity")
    service = default_service if service is None else service
    _validate_service(service)
    if argument is not None and arguments:
        raise ValueError("GESTALT argument sources conflict")
    argument_values = (argument,) if argument is not None else arguments
    if verb is None and (noun is not None or argument_values) or noun is None and argument_values:
        raise ValueError("GESTALT coordinate dependencies are invalid")
    segments = [signal] if without_identity else [signal, service]
    if verb is not None:
        segments.append(f"{verb_glyph} {verb.upper()}")
    if noun is not None:
        segments.append(f"{noun_glyph} {noun.upper()}")
    for value in argument_values:
        value = _semantic_value(value, separator)
        rendered_value = value if '"' in value or "`" in value else value.upper()
        segments.append(f"{argument_glyph} {rendered_value}")
    for glyph, values in ((evidence_glyph, evidence), (datum_glyph, data)):
        segments.extend(f"{glyph} {_semantic_value(value, separator)}" for value in values)
    for value in timing:
        value = _semantic_value(value, separator)
        timing_signal, separator_found, timing_value = value.partition(" ")
        segments.append(
            value
            if separator_found and timing_signal in signals and timing_signal != timing_glyph and timing_value
            else f"{timing_glyph} {value}"
        )
    for continuation in continuations:
        _validate_service(continuation)
        segments.append(f"{action_glyph} {continuation}")
    for delimiter, values in (('"', intents), ('`', cli)):
        for value in values:
            _validate_continuation(value, delimiter)
            segments.append(f"{action_glyph} {delimiter}{value}{delimiter}")
    for action in actions:
        action_verb = action.get("verb")
        action_noun = action.get("noun")
        action_arguments = action.get("arguments", ())
        if "argument" in action:
            if action_arguments:
                raise ValueError("GESTALT argument sources conflict")
            action_arguments = () if action["argument"] is None else (action["argument"],)
        label = action.get("label")
        if not isinstance(action_verb, str) or not isinstance(action_arguments, (list, tuple)) or action_noun is None and action_arguments:
            raise ValueError("GESTALT action coordinate is invalid")
        action_segments = [f"{action_glyph} {default_service}", f"{verb_glyph} {action_verb.upper()}"]
        if isinstance(action_noun, str):
            action_segments.append(f"{noun_glyph} {action_noun.upper()}")
        for value in action_arguments:
            action_segments.append(f"{argument_glyph} {_semantic_value(value, separator)}")
        if isinstance(label, str):
            action_segments.append(f"{evidence_glyph} {_semantic_value(label, separator)}")
        segments.extend(action_segments)
    rendered = separator.join(segments)
    _reject_json(rendered)
    return rendered


def parse_stream(root: Path, value: str) -> dict[str, object]:
    _reject_json(value)
    contract = _segments_contract(root)
    separator = contract["separator"]
    glyphs = contract["glyphs"]
    parts = _stream_parts(value, separator, glyphs["action"])
    if not parts or parts[0] not in contract["signals"]:
        raise ValueError("GESTALT signal is invalid")
    stream: dict[str, object] = {
        "signal": parts[0],
        "service": None,
        "verb": None,
        "noun": None,
        "arguments": [],
        "evidence": [],
        "data": [],
        "timing": [],
        "continuations": [],
        "intents": [],
        "cli": [],
        "actions": [],
    }
    index = 1
    if index < len(parts) and _is_service(parts[index]):
        stream["service"] = parts[index]
        index += 1
    index = _parse_coordinate(parts, index, glyphs, stream)
    while index < len(parts):
        part = parts[index]
        action_prefix = f'{glyphs["action"]} '
        if part.startswith(action_prefix):
            payload = part[len(action_prefix):]
            if payload.startswith(('"', '`')):
                delimiter = payload[0]
                if len(payload) < 2 or not payload.endswith(delimiter):
                    raise ValueError("GESTALT CYOA quote is unclosed")
                _validate_continuation(payload[1:-1], delimiter)
                stream["intents" if delimiter == '"' else "cli"].append(payload[1:-1])
                index += 1
                continue
        if part.startswith(action_prefix) and _is_service(part[len(action_prefix):]):
            action_service = part[len(action_prefix):]
            verb_prefix = f'{glyphs["verb"]} '
            if index + 1 >= len(parts) or not parts[index + 1].startswith(verb_prefix):
                stream["continuations"].append(action_service)
                index += 1
                continue
            if action_service != glyphs["service"]:
                raise ValueError("GESTALT executable action service is not LUCID")
            action: dict[str, object] = {
                "verb": None,
                "noun": None,
                "arguments": [],
                "label": None,
            }
            index = _parse_coordinate(parts, index + 1, glyphs, action)
            if not isinstance(action["verb"], str):
                raise ValueError("GESTALT action verb is absent")
            evidence_prefix = f'{glyphs["evidence"]} '
            if index < len(parts) and parts[index].startswith(evidence_prefix):
                action["label"] = parts[index][len(evidence_prefix):]
                index += 1
            stream["actions"].append(action)
            continue
        relation = next(
            (
                (field, glyph)
                for field, glyph in (
                    ("evidence", glyphs["evidence"]),
                    ("data", glyphs["datum"]),
                    ("timing", glyphs["timing"]),
                )
                if part.startswith(f"{glyph} ")
            ),
            None,
        )
        if relation is None:
            timing_signal, separator_found, timing_value = part.partition(" ")
            if (
                separator_found
                and timing_signal in contract["signals"]
                and timing_signal != glyphs["timing"]
                and timing_value
            ):
                stream["timing"].append(part)
                index += 1
                continue
            raise ValueError("GESTALT segment is not canonical")
        field, glyph = relation
        stream[field].append(part[len(glyph) + 1:])
        index += 1
    return stream


def _stream_parts(value: str, separator: str, action_glyph: str) -> list[str]:
    if "\r" in value or "\n" in value:
        raise ValueError("GESTALT stream must be one physical line")
    remaining = value
    parts = []
    action_prefix = f"{action_glyph} "
    while True:
        trimmed = remaining.lstrip()
        payload = trimmed[len(action_prefix):] if trimmed.startswith(action_prefix) else ""
        if payload.startswith(('"', '`')):
            closing = payload.find(payload[0], 1)
            if closing < 0:
                raise ValueError("GESTALT CYOA quote is unclosed")
            end = len(remaining) - len(trimmed) + len(action_prefix) + closing + 1
            suffix = remaining[end:]
            if not suffix.strip():
                parts.append(remaining.strip())
                return parts
            boundary = suffix.find(separator)
            if boundary < 0 or suffix[:boundary].strip():
                raise ValueError("GESTALT CYOA has trailing unsegmented text")
            boundary += end
        else:
            boundary = remaining.find(separator)
            if boundary < 0:
                parts.append(remaining.strip())
                return parts
        parts.append(remaining[:boundary].strip())
        remaining = remaining[boundary + len(separator):]


def _validate_continuation(value: str, delimiter: str) -> None:
    if (not isinstance(value, str) or not value or len(value.encode("utf-8")) > 1024
        or delimiter in value or any(ord(character) < 32 or 127 <= ord(character) <= 159 for character in value)):
        raise ValueError("GESTALT CYOA continuation is invalid")
    _reject_json(value)


def _validate_service(value: str) -> None:
    if (
        not value
        or len(value.encode("utf-8")) > 64
        or any(character.isspace() or character.isascii() for character in value)
    ):
        raise ValueError("GESTALT service is not a bounded glyph")


def _is_service(value: str) -> bool:
    try:
        _validate_service(value)
    except ValueError:
        return False
    return True


def _parse_coordinate(
    parts: list[str],
    index: int,
    glyphs: dict[str, str],
    target: dict[str, object],
) -> int:
    for field in ("verb", "noun"):
        prefix = f"{glyphs[field]} "
        if index < len(parts) and parts[index].startswith(prefix):
            value = parts[index][len(prefix):]
            target[field] = value.lower() if field in {"verb", "noun"} else value
            index += 1
    prefix = f'{glyphs["argument"]} '
    arguments = []
    while index < len(parts) and parts[index].startswith(prefix):
        arguments.append(parts[index][len(prefix):])
        index += 1
    target["arguments"] = arguments
    if target.get("noun") is not None and target.get("verb") is None:
        raise ValueError("GESTALT noun requires a verb")
    if arguments and target.get("noun") is None:
        raise ValueError("GESTALT argument requires a noun")
    return index


def _segments_contract(root: Path) -> dict[str, object]:
    path = root / "envelope/GESTALT.json"
    metadata = path.lstat()
    if path.is_symlink() or not path.is_file() or metadata.st_size > _MAX_CONTRACT_BYTES:
        raise ValueError("GESTALT contract is not a bounded regular file")
    contract = json.loads(path.read_text(encoding="utf-8"))
    segments = contract.get("segments") if isinstance(contract, dict) else None
    if not isinstance(segments, dict) or contract.get("schema") != "lucid-gestalt/1":
        raise ValueError("GESTALT segment contract is invalid")
    return segments


def semantic_action(
    root: Path,
    verb: str,
    arguments: dict[str, object],
    label: str,
) -> dict[str, object]:
    path = root / "envelope/GESTALT.json"
    contract = json.loads(path.read_text(encoding="utf-8"))
    registry = contract.get("segments", {}).get("operationSelectors", {})
    selectors = registry.get(verb) if isinstance(registry, dict) else None
    if not isinstance(selectors, list) or not isinstance(arguments, dict):
        raise ValueError("GESTALT operation selectors are invalid")
    selected = next(
        (
            selector
            for selector in selectors
            if isinstance(selector, dict)
            and isinstance(selector.get("path"), str)
            and arguments.get(selector["path"]) is not None
        ),
        None,
    )
    if not arguments:
        return {"verb": verb, "arguments": [], "label": label}
    if set(arguments) == {"help"} and isinstance(arguments["help"], str):
        return {"verb": verb, "noun": "help", "arguments": [_semantic_value(arguments["help"], contract["segments"]["separator"]).upper()], "label": label}
    if selected is None:
        raise ValueError("GESTALT semantic noun mapping unavailable")
    selector = selected["path"]
    noun_from = selected.get("nounFrom")
    selected_value = arguments[selector]
    if noun_from == "value" and isinstance(selected_value, str) and selected_value:
        noun = selected_value
    elif noun_from == "key":
        noun = selector
    else:
        raise ValueError("GESTALT operation selector noun source is invalid")
    residual = {
        key: value
        for key, value in arguments.items()
        if not (key == "scope" and value == "this") and (noun_from != "value" or key != selector)
    }
    for token, fields in selected.get("argumentForms", {}).get(noun, {}).items():
        if fields == residual:
            return {"verb": verb, "noun": noun, "arguments": [token], "label": label}
    argument_from = selected.get("argumentFrom")
    if isinstance(argument_from, str) and argument_from:
        value = _argument_at(residual, argument_from)
        if value is not _ABSENT:
            reconstructed = {}
            _insert_argument(reconstructed, argument_from, value)
            if reconstructed == residual:
                encoded = _encode_argument(value, "token" if selected.get("argumentEncoding") == "token" else "text")
                return {"verb": verb, "noun": noun, "arguments": [encoded], "label": label}
    policy = contract.get("semanticArguments", {})
    if policy.get("jsonContainers") != "forbidden":
        raise ValueError("GESTALT semantic argument policy is unavailable")
    mappings = policy.get("bindings", {}).get(verb, {})
    bindings = list(mappings.get(noun, mappings.get("*", [])))
    if not bindings and noun_from == "key":
        bindings.append([selector, "", "scalar"])
    bindings.extend(mappings.get("+", []))
    bindings.append(["scope", "SCOPE", "text"])
    reconstructed = {}
    atoms = []
    for path, prefix, kind in bindings:
        value = _argument_at(residual, path)
        if value is _ABSENT:
            continue
        values = value if kind == "texts" else [value]
        if not isinstance(values, list) or not values:
            raise ValueError("GESTALT repeated argument requires nonempty text values")
        for item in values:
            encoded = _encode_argument(item, "text" if kind == "texts" else kind)
            atoms.append(f"{prefix} {encoded}" if prefix else encoded)
        _insert_argument(reconstructed, path, value)
    if reconstructed != residual:
        raise ValueError(f"GESTALT semantic argument mapping unavailable for {verb.upper()} {noun.upper()}")
    return {"verb": verb, "noun": noun, "arguments": atoms, "label": label}


_ABSENT = object()


def _argument_at(value: dict, path: str) -> object:
    for key in path.split("."):
        if not isinstance(value, dict) or key not in value:
            return _ABSENT
        value = value[key]
    return value


def _insert_argument(target: dict, path: str, value: object) -> None:
    keys = path.split(".")
    for key in keys[:-1]:
        target = target.setdefault(key, {})
    target[keys[-1]] = value


def _encode_argument(value: object, kind: str) -> str:
    if isinstance(value, str) and kind in {"text", "token", "scalar"}:
        _reject_json(value)
        if kind == "token":
            if not value or any(character.isspace() for character in value):
                raise ValueError("GESTALT token must be nonempty and unspaced")
            if value == value.lower():
                return value.upper()
        if value and all(not character.isascii() and not character.isspace() for character in value):
            return value
        delimiter = "`" if "`" not in value else '"'
        if delimiter in value or any(ord(character) < 32 for character in value):
            raise ValueError("GESTALT literal requires a separate source artifact")
        return f"{delimiter}{value}{delimiter}"
    if kind == "scalar" and isinstance(value, bool):
        return "ON" if value else "OFF"
    if kind in {"integer", "scalar"} and isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    raise ValueError("GESTALT argument needs a registered semantic form, not a JSON value")


def _semantic_value(value: str, separator: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("GESTALT semantic value is invalid")
    value = value.replace("\r", " ").replace("\n", " ")
    _reject_json(value)
    if separator in value:
        raise ValueError("GESTALT semantic value contains the canonical separator; use separate semantic fields")
    return value


def _reject_json(value: str) -> None:
    decoder = json.JSONDecoder()
    pending = [(value, 0)]
    while pending:
        text, depth = pending.pop()
        if depth > 32:
            raise ValueError("GESTALT literal nesting exceeds its bound")
        for offset, character in enumerate(text):
            if character not in '{["':
                continue
            if character == "[" and offset and (text[offset - 1].isalnum() or text[offset - 1] in "$_.]"):
                index, closing, _ = text[offset + 1:].partition("]")
                if closing and index and index.isascii() and index.isdecimal():
                    continue
            try:
                decoded, _ = decoder.raw_decode(text, offset)
            except (ValueError, RecursionError):
                continue
            if isinstance(decoded, (dict, list)):
                raise ValueError("JSON is transport data, not canonical GESTALT")
            if isinstance(decoded, str) and len(decoded) < len(text):
                pending.append((decoded, depth + 1))