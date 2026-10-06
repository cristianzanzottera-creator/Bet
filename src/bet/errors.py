"""Errori sui file scritti dall'utente: strategie, scenari, configurazione."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError


class InputError(Exception):
    """File non valido: il messaggio spiega cosa correggere."""


def load_yaml(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise InputError(f"{path}: impossibile leggere il file ({exc.strerror})") from None
    except yaml.YAMLError as exc:
        raise InputError(f"{path}: YAML non valido\n{exc}") from None


def format_errors(exc: ValidationError) -> str:
    lines = []
    for error in exc.errors():
        where = ".".join(str(part) for part in error["loc"]) or "file"
        lines.append(f"  - {where}: {_message(error)}")
    return "\n".join(lines)


def _message(error: Any) -> str:
    ctx = error.get("ctx", {})
    match error["type"]:
        case "missing":
            return "campo obbligatorio mancante"
        case "extra_forbidden":
            return "campo non previsto (controlla come è scritto)"
        case "value_error":
            return str(ctx.get("error", error["msg"]))
        case "literal_error":
            return f"valore non ammesso, usa {ctx.get('expected', '').replace(' or ', ' oppure ')}"
        case "greater_than":
            return f"deve essere maggiore di {ctx['gt']}"
        case "greater_than_equal":
            return f"deve essere almeno {ctx['ge']}"
        case "less_than":
            return f"deve essere minore di {ctx['lt']}"
        case "too_short":
            return "non può essere vuoto"
        case "float_parsing" | "float_type" | "int_parsing" | "int_type" | "int_from_float":
            return "deve essere un numero"
        case "bool_parsing" | "bool_type":
            return "deve essere true o false"
        case "string_type":
            return "deve essere un testo"
        case "model_type" | "dict_type" | "model_attributes_type":
            return "deve essere una sezione con campi (chiave: valore)"
        case "list_type":
            return "deve essere un elenco"
    return error["msg"]
