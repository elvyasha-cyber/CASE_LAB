"""Рабочий вход: письма из папки JSON."""

from __future__ import annotations

from pathlib import Path

from case_lab.loaders import SourceProblem, load_inbox
from case_lab.schemas import InboundEmail


def load_file_inbox(folder: Path) -> list[InboundEmail | SourceProblem]:
    return load_inbox(folder)
