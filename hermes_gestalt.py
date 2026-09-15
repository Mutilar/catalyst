"""Canonical GESTALT semantic stream projection from the AgentExperiments SOT."""

from __future__ import annotations

import json
from pathlib import Path
from string import ascii_lowercase, ascii_uppercase

_MAX_CONTRACT_BYTES = 64 * 1024
_UPPERCASE = str.maketrans(ascii_lowercase, ascii_uppercase)
_LOWERCASE = str.maketrans(ascii_uppercase, ascii_lowercase)


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
    continuations: tuple[str | dict[str, str], ...] = (),
    intents: tuple[str, ...] = (),
    cli: tuple[str, ...] = (),
    actions: tuple[dict[str, object], ...] = (),
) -> str:
    contract = _contract(root)
    header = contract["segments"]
    glyphs = header["glyphs"]
    signals = header["signals"]
    if signal not in signals:
        raise ValueError("GESTALT signal is not canonical")
    if without_identity and service is not None:
        raise ValueError("GESTALT service conflicts with without_identity")
    service = glyphs["service"] if service is None else service
    _validate_service(service, contract)
    for values in (evidence, data, timing, continuations, intents, cli, actions):
        if not isinstance(values, (list, tuple)):
            raise ValueError("GESTALT repeated fields require arrays")
    argument_values = _arguments(argument, arguments)
    segments = [signal] if without_identity else [signal, service]
    segments.extend(_coordinate(verb, noun, argument_values, contract))
    for glyph, values in ((glyphs["evidence"], evidence), (glyphs["datum"], data)):
        segments.extend(f"{glyph} {_semantic_value(value, contract)}" for value in values)
    for value in timing:
        value = _semantic_value(value, contract)
        timing_signal, separator_found, timing_value = value.partition(" ")
        segments.append(
            value
            if separator_found and timing_signal in signals and timing_value
            else f'{glyphs["timing"]} {value}'
        )
    ordered_continuations = [
        {"kind": "service", "value": entry} if isinstance(entry, str) else entry
        for entry in continuations
    ]
    for continuation in ordered_continuations:
        if not isinstance(continuation, dict) or set(continuation) != {"kind", "value"}:
            raise ValueError("GESTALT CYOA continuation is invalid")
        kind, value = continuation["kind"], continuation["value"]
        if kind == "service":
            _validate_service(value, contract)
        elif kind in ("cli", "intent"):
            delimiter = "`" if kind == "cli" else '"'
            _validate_continuation(value, delimiter)
            value = f"{delimiter}{value}{delimiter}"
        else:
            raise ValueError("GESTALT CYOA continuation is invalid")
        segments.append(f'{glyphs["action"]} {value}')
    for delimiter, kind, values in (('"', "intent", intents), ('`', "cli", cli)):
        represented = [entry["value"] for entry in ordered_continuations if entry["kind"] == kind]
        if represented and values:
            if represented != list(values):
                raise ValueError("GESTALT CYOA continuation sources conflict")
            continue
        for value in values:
            _validate_continuation(value, delimiter)
            segments.append(f'{glyphs["action"]} {delimiter}{value}{delimiter}')
    for action in actions:
        if not isinstance(action, dict) or action.get("service", glyphs["service"]) != glyphs["service"]:
            raise ValueError("GESTALT executable action service is not LUCID")
        action_verb = action.get("verb")
        if action_verb not in header["verbs"]:
            raise ValueError("GESTALT action verb is not canonical")
        action_arguments = _arguments(action.get("argument"), action.get("arguments", ()))
        segments.append(f'{glyphs["action"]} {glyphs["service"]}')
        segments.extend(_coordinate(action_verb, action.get("noun"), action_arguments, contract))
        label = action.get("label")
        if label is not None:
            segments.append(f'{glyphs["evidence"]} {_semantic_value(label, contract)}')
    return header["separator"].join(segments)


def parse_stream(root: Path, value: str) -> dict[str, object]:
    contract = _contract(root)
    header = contract["segments"]
    glyphs = header["glyphs"]
    parts = _stream_parts(value, contract)
    if not parts or parts[0] not in header["signals"]:
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
    if index < len(parts) and _is_service(parts[index], contract):
        stream["service"] = parts[index]
        index += 1
    index = _parse_coordinate(parts, index, contract, stream)
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
                stream["continuations"].append(
                    {"kind": "intent" if delimiter == '"' else "cli", "value": payload[1:-1]}
                )
                stream["intents" if delimiter == '"' else "cli"].append(payload[1:-1])
                index += 1
                continue
            action_service = part[len(action_prefix):]
            _validate_service(action_service, contract)
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
            index = _parse_coordinate(parts, index + 1, contract, action)
            if not isinstance(action["verb"], str):
                raise ValueError("GESTALT action verb is absent")
            evidence_prefix = f'{glyphs["evidence"]} '
            if index < len(parts) and parts[index].startswith(evidence_prefix):
                action["label"] = _semantic_value(parts[index][len(evidence_prefix):], contract)
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
                and timing_signal in header["signals"]
                and timing_signal != glyphs["timing"]
                and timing_value
            ):
                stream["timing"].append(_semantic_value(part, contract))
                index += 1
                continue
            raise ValueError("GESTALT segment is not canonical")
        field, glyph = relation
        stream[field].append(_semantic_value(part[len(glyph) + 1:], contract))
        index += 1
    if stream["service"] is None:
        stream["without_identity"] = True
    return stream


def _stream_parts(value: str, contract: dict) -> list[str]:
    if not isinstance(value, str) or "\r" in value or "\n" in value:
        raise ValueError("GESTALT stream must be one physical line")
    separator = contract["segments"]["separator"]
    remaining = value
    parts = []
    action_prefix = f'{contract["segments"]["glyphs"]["action"]} '
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
            boundary = _separator_outside_literals(remaining, [separator], contract)
            if boundary is None:
                parts.append(remaining.strip())
                return parts
        parts.append(remaining[:boundary].strip())
        remaining = remaining[boundary + len(separator):]


def _validate_continuation(value: str, delimiter: str) -> None:
    if (not isinstance(value, str) or not value or len(value.encode("utf-8")) > 1024
        or delimiter in value or any(ord(character) < 32 or 127 <= ord(character) <= 159 for character in value)):
        raise ValueError("GESTALT CYOA continuation is invalid")
    _reject_json(value)


def _validate_service(value: str, contract: dict) -> None:
    header = contract["segments"]
    if (
        not isinstance(value, str)
        or not value
        or len(value.encode("utf-8")) > 64
        or value.isascii()
        or any(character.isspace() or character.isalnum() or ord(character) < 32 or 127 <= ord(character) <= 159 for character in value)
        or value in header["signals"]
        or value in [glyph for field, glyph in header["glyphs"].items() if field != "service"]
    ):
        raise ValueError("GESTALT service is not a bounded glyph")
    _reject_json(value)


def _is_service(value: str, contract: dict) -> bool:
    try:
        _validate_service(value, contract)
    except ValueError:
        return False
    return True


def _parse_coordinate(
    parts: list[str],
    index: int,
    contract: dict,
    target: dict[str, object],
) -> int:
    glyphs = contract["segments"]["glyphs"]
    for field in ("verb", "noun"):
        prefix = f"{glyphs[field]} "
        if index < len(parts) and parts[index].startswith(prefix):
            value = parts[index][len(prefix):]
            target[field] = value.translate(_LOWERCASE)
            index += 1
    prefix = f'{glyphs["argument"]} '
    arguments = []
    while index < len(parts) and parts[index].startswith(prefix):
        arguments.append(parts[index][len(prefix):])
        index += 1
    target["arguments"] = arguments
    _coordinate(target.get("verb"), target.get("noun"), arguments, contract)
    return index


def _arguments(argument: str | None, arguments) -> list[str]:
    if not isinstance(arguments, (list, tuple)):
        raise ValueError("GESTALT arguments require an array")
    values = list(arguments)
    if argument is not None:
        if values and values != [argument]:
            raise ValueError("GESTALT argument sources conflict")
        values = [argument]
    return values


def _coordinate(verb, noun, arguments: list[str], contract: dict) -> list[str]:
    if verb == "" and noun is None and not arguments:
        return []
    if verb is None and (noun is not None or arguments) or noun is None and arguments:
        raise ValueError("GESTALT coordinate dependencies are invalid")
    header = contract["segments"]
    glyphs = header["glyphs"]
    parts = []
    if verb is not None:
        if verb not in header["verbs"]:
            raise ValueError("GESTALT verb is not canonical")
        parts.append(f'{glyphs["verb"]} {verb.translate(_UPPERCASE)}')
    if noun is not None:
        parts.append(f'{glyphs["noun"]} {_semantic_value(noun, contract).translate(_UPPERCASE)}')
    for value in arguments:
        value = _semantic_value(value, contract)
        rendered = value if '"' in value or "`" in value else value.translate(_UPPERCASE)
        parts.append(f'{glyphs["argument"]} {rendered}')
    return parts


def _contract(root: Path) -> dict[str, object]:
    path = root / "envelope/GESTALT.json"
    metadata = path.lstat()
    if path.is_symlink() or not path.is_file() or metadata.st_size > _MAX_CONTRACT_BYTES:
        raise ValueError("GESTALT contract is not a bounded regular file")
    contract = json.loads(path.read_text(encoding="utf-8"))
    header = contract.get("segments") if isinstance(contract, dict) else None
    fields = ["signal", "service", "verb", "noun", "argument", "evidence", "datum", "timing", "action"]
    if (
        not isinstance(header, dict)
        or contract.get("schema") != "lucid-gestalt/1"
        or header.get("order") != fields
        or header.get("required") != ["signal"]
        or header.get("optional") != fields[1:]
        or header.get("repeatable") != ["argument", "evidence", "datum", "timing", "action"]
        or not isinstance(header.get("glyphs"), dict)
        or not all(isinstance(header["glyphs"].get(field), str) and header["glyphs"][field] for field in fields[1:])
        or not isinstance(header.get("separator"), str)
        or not header["separator"]
        or not isinstance(header.get("signals"), list)
        or len(header["signals"]) != 4
        or not all(isinstance(signal, str) and signal for signal in header["signals"])
        or not isinstance(header.get("verbs"), list)
        or not all(isinstance(verb, str) and verb for verb in header["verbs"])
        or set(header["verbs"]) != set(header.get("operationSelectors", {}))
        or not isinstance(contract.get("lint", {}).get("alternateSeparators"), list)
        or not all(isinstance(value, str) and value for value in contract["lint"]["alternateSeparators"])
        or not isinstance(contract.get("recovery", {}).get("bounds", {}).get("nesting"), int)
        or contract["recovery"]["bounds"]["nesting"] <= 0
    ):
        raise ValueError("GESTALT segment contract is invalid")
    return contract


def semantic_action(
    root: Path,
    verb: str,
    arguments: dict[str, object],
    label: str,
) -> dict[str, object]:
    contract = _contract(root)
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
        return {"verb": verb, "noun": "help", "arguments": [_semantic_value(arguments["help"], contract).translate(_UPPERCASE)], "label": label}
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


def _semantic_value(value: str, contract: dict) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("GESTALT semantic value is invalid")
    if "\r" in value or "\n" in value:
        parts = []
        remaining = value
        while (boundary := _separator_outside_literals(remaining, ["\r", "\n"], contract)) is not None:
            parts.extend((remaining[:boundary], " "))
            remaining = remaining[boundary + 1:]
        parts.append(remaining)
        value = "".join(parts)
        if "\r" in value or "\n" in value:
            raise ValueError("GESTALT literal requires single-line source")
    _reject_json(value)
    if _separator_outside_literals(value, [contract["segments"]["separator"]], contract) is not None:
        raise ValueError("GESTALT semantic value contains the canonical separator; use separate semantic fields")
    if _separator_outside_literals(value, contract["lint"]["alternateSeparators"], contract) is not None:
        raise ValueError("GESTALT semantic value contains an alternate separator; use separate semantic fields")
    return value


def _separator_outside_literals(value: str, separators: list[str], contract: dict) -> int | None:
    quote = None
    quote_run = 0
    brackets = []
    escaped = False
    offset = 0
    while offset < len(value):
        character = value[offset]
        run = 1
        if character in "`$":
            while offset + run < len(value) and value[offset + run] == character:
                run += 1
        next_offset = offset + run
        if escaped:
            escaped = False
        elif character == "\\":
            escaped = True
        elif quote is not None:
            if character == quote and run == quote_run:
                quote = None
        elif character == "$" and run == 1 and next_offset < len(value) and value[next_offset] in "[.":
            pass
        elif character in '\"`$\u201c\u2018' or character == "'" and not (
            offset and value[offset - 1].isalnum() and next_offset < len(value) and value[next_offset].isalnum()
        ):
            quote = {"\u201c": "\u201d", "\u2018": "\u2019"}.get(character, character)
            quote_run = run
        elif character in "([{":
            if len(brackets) == contract["recovery"]["bounds"]["nesting"]:
                return None
            brackets.append({"(": ")", "[": "]", "{": "}"}[character])
        elif character in ")]}":
            if not brackets or brackets.pop() != character:
                return None
        elif not brackets and any(value.startswith(separator, offset) for separator in separators):
            return offset
        offset = next_offset
    return None


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