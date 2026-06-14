from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ModelPreviewReport:
    blend_file: Path
    preview_image_path: Path
    triangle_count: int
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    @property
    def is_successful(self) -> bool:
        return not self.errors
