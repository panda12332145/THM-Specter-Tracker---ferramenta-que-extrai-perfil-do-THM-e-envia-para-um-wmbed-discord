"""Persistência atômica dos dados extraídos em arquivo JSON."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Union


def save_json(data: Dict[str, Any], output_path: Union[str, Path] = "tryhackme_profile.json") -> Path:
    """Salva o dicionário em JSON UTF-8 de forma atômica (tmp + os.replace)."""
    target = Path(output_path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target.with_name(f"{target.name}.tmp")

    with open(tmp_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=4, ensure_ascii=False)
        fh.write("\n")

    os.replace(tmp_path, target)
    return target
