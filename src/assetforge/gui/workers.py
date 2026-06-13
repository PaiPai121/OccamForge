from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from assetforge.domain.analysis import VehicleAnalysisReport
from assetforge.domain.optimization import VehicleOptimizationReport
from assetforge.services.vehicle_analysis import VehicleAnalysisService
from assetforge.services.vehicle_optimization import VehicleOptimizationService


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
