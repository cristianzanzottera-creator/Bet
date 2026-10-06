"""Impostazioni generali: bankroll, commissione, limiti di rischio."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .errors import InputError, format_errors, load_yaml


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["paper"] = Field("paper", alias="modalita")
    """Per ora solo simulazione; il live arriverà con l'adattatore Betfair."""
    bankroll: float = Field(1000.0, gt=0)
    commission: float = Field(0.05, ge=0, lt=1, alias="commissione")
    """Commissione sulle vincite nette di ogni mercato."""
    min_stake: float = Field(2.0, gt=0, alias="puntata_minima")
    max_exposure: float | None = Field(None, gt=0, alias="esposizione_massima")
    """Perdita massima possibile sommando posizioni aperte e ordini in attesa."""


def load_settings(path: Path | None) -> Settings:
    if path is None:
        return Settings()
    data = load_yaml(path) or {}
    try:
        return Settings.model_validate(data)
    except ValidationError as exc:
        raise InputError(f"{path}: configurazione non valida\n{format_errors(exc)}") from None
