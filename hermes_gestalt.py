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
    evidence: tuple[str, ...] = (),
    data: tuple[str, ...] = (),
    timing: tuple[str, ...] = (),
    continuations: tuple[str, ...] = (),
    actions: tuple[dict[str, str | None], ...] = (),
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
    service = default_service if service is None else service
    _validate_service(service)
    canonical_argument = (
        argument
        if argument is None or argument.startswith(('"', "{", "["))
        else argument.upper()
    )
    if verb is None and (noun is not None or argument is not None) or noun is None and argument is not None:
        raise ValueError("GESTALT coordinate dependencies are invalid")
    segments = [signal, service]
    if verb is not None:
        segments.append(f"{verb_glyph} {verb.upper()}")
    if noun is not None:
        segments.append(f"{noun_glyph} {noun.upper()}")
    if canonical_argument is not None:
        segments.append(f"{argument_glyph} {canonical_argument}")
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
    for action in actions:
        action_verb = action.get("verb")
        action_noun = action.get("noun")
        action_argument = action.get("argument")
        label = action.get("label")
        if not isinstance(action_verb, str) or action_noun is None and action_argument is not None:
            raise ValueError("GESTALT action coordinate is invalid")
        action_segments = [f"{action_glyph} {default_service}", f"{verb_glyph} {action_verb.upper()}"]
        if isinstance(action_noun, str):
            action_segments.append(f"{noun_glyph} {action_noun.upper()}")
        if isinstance(action_argument, str):
            action_segments.append(f"{argument_glyph} {action_argument}")
        if isinstance(label, str):
            action_segments.append(f"{evidence_glyph} {_semantic_value(label, separator)}")
        segments.extend(action_segments)
    return separator.join(segments)


def parse_stream(root: Path, value: str) -> dict[str, object]:
    contract = _segments_contract(root)
    separator = contract["separator"]
    glyphs = contract["glyphs"]
    parts = [part.strip() for part in value.split(separator)]
    if not parts or parts[0] not in contract["signals"]:
        raise ValueError("GESTALT signal is invalid")
    stream: dict[str, object] = {
        "signal": parts[0],
        "service": None,
        "verb": None,
        "noun": None,
        "argument": None,
        "evidence": [],
        "data": [],
        "timing": [],
        "continuations": [],
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
                "argument": None,
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
    for field in ("verb", "noun", "argument"):
        prefix = f"{glyphs[field]} "
        if index < len(parts) and parts[index].startswith(prefix):
            value = parts[index][len(prefix):]
            target[field] = value.lower() if field in {"verb", "noun"} else value
            index += 1
    if target.get("noun") is not None and target.get("verb") is None:
        raise ValueError("GESTALT noun requires a verb")
    if target.get("argument") is not None and target.get("noun") is None:
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
) -> dict[str, str | None]:
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
    if selected is None:
        fallback = next(((key, value) for key, value in arguments.items() if key != "scope" and value is not None), None)
        if fallback is None:
            return {"verb": verb, "label": label}
        key, value = fallback
        return {
            "verb": verb,
            "noun": key,
            "argument": _canonical_json(value),
            "label": label,
        }
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
        if key != "scope" and value is not None and (noun_from != "value" or key != selector)
    }
    projected_argument: object | None = arguments
    argument_from = selected.get("argumentFrom")
    if isinstance(argument_from, str) and argument_from:
        path = argument_from.split(".")
        for key in path:
            projected_argument = (
                projected_argument.get(key)
                if isinstance(projected_argument, dict)
                else None
            )
        if projected_argument is not None:
            residual.pop(path[0], None)
    else:
        projected_argument = None
    if projected_argument is not None and not residual:
        argument = (
            str(projected_argument).upper()
            if selected.get("argumentEncoding") == "token"
            else _canonical_json(projected_argument)
        )
    elif noun_from == "key" and len(residual) == 1:
        argument = _canonical_json(selected_value)
    elif residual:
        argument = _canonical_json(residual)
    else:
        argument = None
    return {"verb": verb, "noun": noun, "argument": argument, "label": label}


def _semantic_value(value: str, separator: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("GESTALT semantic value is invalid")
    value = value.replace("\r", " ").replace("\n", " ")
    if separator in value:
        raise ValueError("GESTALT semantic value contains the canonical separator; use separate semantic fields")
    return value


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)