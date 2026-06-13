from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from assetforge.domain.analysis import VehicleAnalysisReport
from assetforge.domain.build import CitiesSkylinesBuildReport
from assetforge.domain.export import VehicleExportReport
from assetforge.domain.optimization import VehicleOptimizationReport
from assetforge.domain.validation import ValidationReport
from assetforge.services.vehicle_analysis import VehicleAnalysisService
from assetforge.services.vehicle_export import VehicleExportService
from assetforge.services.vehicle_optimization import VehicleOptimizationService
from assetforge.services.vehicle_validation import VehicleValidationService


class AnalysisWorkerSignals(QObject):
    started = Signal()
    finished = Signal(object)
    failed = Signal(str)


class AnalysisWorker(QRunnable):
    def __init__(self, service: VehicleAnalysisService, blend_file: Path) -> None:
        super().__init__()
        self._service = service
        self._blend_file = blend_file
        self.signals = AnalysisWorkerSignals()

    @Slot()
    def run(self) -> None:
        self.signals.started.emit()
        try:
            report: VehicleAnalysisReport = self._service.analyze_vehicle(self._blend_file)
        except Exception as exc:  # noqa: BLE001 - show infrastructure failures in GUI.
            self.signals.failed.emit(str(exc))
            return
        self.signals.finished.emit(report)


class OptimizationWorkerSignals(QObject):
    started = Signal()
    progress = Signal(str)
    analysis_finished = Signal(object)
    finished = Signal(object)
    failed = Signal(str)


class OptimizationWorker(QRunnable):
    def __init__(
        self,
        analysis_service: VehicleAnalysisService,
        optimization_service: VehicleOptimizationService,
        blend_file: Path,
        profile_id: str,
        target_triangle_count: int,
    ) -> None:
        super().__init__()
        self._analysis_service = analysis_service
        self._optimization_service = optimization_service
        self._blend_file = blend_file
        self._profile_id = profile_id
        self._target_triangle_count = target_triangle_count
        self.signals = OptimizationWorkerSignals()

    @Slot()
    def run(self) -> None:
        self.signals.started.emit()
        try:
            self.signals.progress.emit("Analyzing selected file...")
            analysis_report: VehicleAnalysisReport = self._analysis_service.analyze_vehicle(
                self._blend_file
            )
            self.signals.analysis_finished.emit(analysis_report)
            if analysis_report.errors:
                self.signals.failed.emit("\n".join(analysis_report.errors))
                return

            self.signals.progress.emit("Optimizing copied blend file...")
            optimization_report: VehicleOptimizationReport = (
                self._optimization_service.optimize_vehicle(
                    self._blend_file,
                    self._profile_id,
                    self._target_triangle_count,
                )
            )
        except Exception as exc:  # noqa: BLE001 - show infrastructure failures in GUI.
            self.signals.failed.emit(str(exc))
            return
        self.signals.finished.emit(optimization_report)


class ExportWorkerSignals(QObject):
    started = Signal()
    progress = Signal(str)
    validation_finished = Signal(object)
    finished = Signal(object)
    failed = Signal(str)


class ValidationWorkerSignals(QObject):
    started = Signal()
    progress = Signal(str)
    finished = Signal(object)
    failed = Signal(str)


class ValidationWorker(QRunnable):
    def __init__(
        self,
        validation_service: VehicleValidationService,
        blend_file: Path,
        profile_id: str,
    ) -> None:
        super().__init__()
        self._validation_service = validation_service
        self._blend_file = blend_file
        self._profile_id = profile_id
        self.signals = ValidationWorkerSignals()

    @Slot()
    def run(self) -> None:
        self.signals.started.emit()
        try:
            self.signals.progress.emit("Validating selected file...")
            validation_report = self._validation_service.validate_vehicle(
                self._blend_file,
                self._profile_id,
            )
        except Exception as exc:  # noqa: BLE001 - show infrastructure failures in GUI.
            self.signals.failed.emit(str(exc))
            return
        self.signals.finished.emit(validation_report)


class ExportWorker(QRunnable):
    def __init__(
        self,
        validation_service: VehicleValidationService,
        export_service: VehicleExportService,
        blend_file: Path,
        profile_id: str,
    ) -> None:
        super().__init__()
        self._validation_service = validation_service
        self._export_service = export_service
        self._blend_file = blend_file
        self._profile_id = profile_id
        self.signals = ExportWorkerSignals()

    @Slot()
    def run(self) -> None:
        self.signals.started.emit()
        try:
            validation_blend = self._export_service.preferred_export_blend(self._blend_file)
            self.signals.progress.emit("Validating selected file...")
            validation_report: ValidationReport = self._validation_service.validate_vehicle(
                validation_blend,
                self._profile_id,
            )
            self.signals.validation_finished.emit(validation_report)
            if not validation_report.export_ready:
                self.signals.failed.emit("\n".join(validation_report.messages))
                return

            self.signals.progress.emit("Exporting FBX...")
            export_report: VehicleExportReport = self._export_service.export_fbx(
                self._blend_file,
                self._profile_id,
            )
        except Exception as exc:  # noqa: BLE001 - show infrastructure failures in GUI.
            self.signals.failed.emit(str(exc))
            return
        self.signals.finished.emit(export_report)


class CitiesSkylinesBuildWorkerSignals(QObject):
    started = Signal()
    progress = Signal(str)
    finished = Signal(object)
    failed = Signal(str)


class CitiesSkylinesBuildWorker(QRunnable):
    def __init__(self, build_service: CitiesSkylinesBuildService, blend_file: Path) -> None:
        super().__init__()
        self._build_service = build_service
        self._blend_file = blend_file
        self.signals = CitiesSkylinesBuildWorkerSignals()

    @Slot()
    def run(self) -> None:
        self.signals.started.emit()
        try:
            self.signals.progress.emit("Building Cities Skylines asset package...")
            report: CitiesSkylinesBuildReport = self._build_service.build(self._blend_file)
        except Exception as exc:  # noqa: BLE001 - show infrastructure failures in GUI.
            self.signals.failed.emit(str(exc))
            return
        self.signals.finished.emit(report)
from assetforge.services.cities_skylines_build import CitiesSkylinesBuildService
