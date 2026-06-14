from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from assetforge.domain.model_preview import ModelPreviewReport


class ModelPreviewGenerator(ABC):
    @abstractmethod
    def generate_model_preview(
        self,
        blend_file: Path,
        output_directory: Path,
    ) -> ModelPreviewReport:
        raise NotImplementedError


class ModelPreviewService:
    def __init__(self, generator: ModelPreviewGenerator) -> None:
        self._generator = generator

    def generate(
        self,
        blend_file: Path,
        output_directory: Path | None = None,
    ) -> ModelPreviewReport:
        if not blend_file.exists():
            raise FileNotFoundError(f"Blend file does not exist: {blend_file}")
        if blend_file.suffix.lower() != ".blend":
            raise ValueError(f"Expected a .blend file, got: {blend_file}")
        preview_directory = output_directory or blend_file.parent / "previews"
        return self._generator.generate_model_preview(blend_file, preview_directory)
