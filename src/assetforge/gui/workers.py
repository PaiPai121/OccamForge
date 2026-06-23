from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from assetforge.domain.analysis import VehicleAnalysisReport
from assetforge.domain.build import CitiesSkylinesBuildReport
from assetforge.domain.export import VehicleExportReport
from assetforge.domain.geometry_report import GeometryReport
from assetforge.domain.model_preview import ModelPreviewReport
from assetforge.domain.optimization import VehicleOptimizationReport
from assetforge.domain.optimization_preview import OptimizationPreviewReport
from assetforge.domain.preprocess import PreprocessReport
from assetforge.domain.real_optimization_preview import RealOptimizationPreviewReport
from assetforge.domain.simplification_report import SimplificationReport
from assetforge.domain.validation import ValidationReport
from assetforge.services.afcost_candidates import AFCostCandidateService
from assetforge.services.cities_skylines_build import CitiesSkylinesBuildService
from assetforge.services.geometry_report import GeometryReportService
from assetforge.services.local_simplification import LocalSimplificationService
from assetforge.services.model_preview import ModelPreviewService
from assetforge.services.optimization_preview import OptimizationPreviewService
from assetforge.services.preprocess import PreprocessService
from assetforge.services.qem_heatmap import QemHeatmapService
from assetforge.services.real_optimization_preview import RealOptimizationPreviewService
from assetforge.services.scale_analysis import ScaleAnalysisService
from assetforge.services.simplification_report import SimplificationReportService
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


class PreprocessWorkerSignals(QObject):
    started = Signal()
    progress = Signal(str)
    finished = Signal(object)
    failed = Signal(str)


class PreprocessWorker(QRunnable):
    def __init__(
        self,
        preprocess_service: PreprocessService,
        blend_file: Path,
        angle_degrees: float = 1.0,
    ) -> None:
        super().__init__()
        self._preprocess_service = preprocess_service
        self._blend_file = blend_file
        self._angle_degrees = angle_degrees
        self.signals = PreprocessWorkerSignals()

    @Slot()
    def run(self) -> None:
        self.signals.started.emit()
        try:
            self.signals.progress.emit("Running safe preprocess with Limited Dissolve...")
            report: PreprocessReport = self._preprocess_service.preprocess(
                self._blend_file,
                self._angle_degrees,
            )
        except Exception as exc:  # noqa: BLE001 - show infrastructure failures in GUI.
            self.signals.failed.emit(str(exc))
            return
        self.signals.finished.emit(report)


class OptimizationPreviewWorkerSignals(QObject):
    started = Signal()
    progress = Signal(str)
    analysis_finished = Signal(object)
    finished = Signal(object)
    failed = Signal(str)


class OptimizationPreviewWorker(QRunnable):
    def __init__(
        self,
        analysis_service: VehicleAnalysisService,
        preview_service: OptimizationPreviewService,
        blend_file: Path,
        profile_id: str,
        targets: tuple[int, ...],
    ) -> None:
        super().__init__()
        self._analysis_service = analysis_service
        self._preview_service = preview_service
        self._blend_file = blend_file
        self._profile_id = profile_id
        self._targets = targets
        self.signals = OptimizationPreviewWorkerSignals()

    @Slot()
    def run(self) -> None:
        self.signals.started.emit()
        try:
            self.signals.progress.emit("Analyzing selected file for optimization preview...")
            analysis_report = self._analysis_service.analyze_vehicle(self._blend_file)
            self.signals.analysis_finished.emit(analysis_report)
            if analysis_report.errors:
                self.signals.failed.emit("\n".join(analysis_report.errors))
                return
            report: OptimizationPreviewReport = self._preview_service.preview(
                analysis_report.triangle_count,
                self._profile_id,
                self._targets,
            )
        except Exception as exc:  # noqa: BLE001 - show infrastructure failures in GUI.
            self.signals.failed.emit(str(exc))
            return
        self.signals.finished.emit(report)


class RealOptimizationPreviewWorkerSignals(QObject):
    started = Signal()
    progress = Signal(str)
    finished = Signal(object)
    failed = Signal(str)


class RealOptimizationPreviewWorker(QRunnable):
    def __init__(
        self,
        preview_service: RealOptimizationPreviewService,
        blend_file: Path,
        profile_id: str,
        target_triangle_count: int,
        output_directory: Path,
        pipeline_stage: int = 1,
    ) -> None:
        super().__init__()
        self._preview_service = preview_service
        self._blend_file = blend_file
        self._profile_id = profile_id
        self._target_triangle_count = target_triangle_count
        self._output_directory = output_directory
        self._pipeline_stage = pipeline_stage
        self.signals = RealOptimizationPreviewWorkerSignals()

    @Slot()
    def run(self) -> None:
        self.signals.started.emit()
        try:
            self.signals.progress.emit("Generating real Blender optimization preview...")
            report: RealOptimizationPreviewReport = self._preview_service.generate(
                self._blend_file,
                self._profile_id,
                self._target_triangle_count,
                self._output_directory,
                self._pipeline_stage,
            )
        except Exception as exc:  # noqa: BLE001 - show infrastructure failures in GUI.
            self.signals.failed.emit(str(exc))
            return
        self.signals.finished.emit(report)


class LocalSimplificationWorkerSignals(QObject):
    started = Signal()
    progress = Signal(str)
    finished = Signal(object)
    failed = Signal(str)


class LocalSimplificationWorker(QRunnable):
    def __init__(
        self,
        simplification_service: LocalSimplificationService,
        blend_file: Path,
        profile_id: str,
        target_triangle_count: int,
        output_directory: Path,
        combo_candidate: str = "auto",
    ) -> None:
        super().__init__()
        self._simplification_service = simplification_service
        self._blend_file = blend_file
        self._profile_id = profile_id
        self._target_triangle_count = target_triangle_count
        self._output_directory = output_directory
        self._combo_candidate = combo_candidate
        self.signals = LocalSimplificationWorkerSignals()

    @Slot()
    def run(self) -> None:
        self.signals.started.emit()
        try:
            self.signals.progress.emit("Running local edge-collapse simplification...")
            report: RealOptimizationPreviewReport = self._simplification_service.generate(
                self._blend_file,
                self._profile_id,
                self._target_triangle_count,
                self._output_directory,
                self._combo_candidate,
            )
        except Exception as exc:  # noqa: BLE001 - show infrastructure failures in GUI.
            self.signals.failed.emit(str(exc))
            return
        self.signals.finished.emit(report)


class ModelPreviewWorkerSignals(QObject):
    started = Signal()
    progress = Signal(str)
    finished = Signal(object)
    failed = Signal(str)


class ModelPreviewWorker(QRunnable):
    def __init__(
        self,
        preview_service: ModelPreviewService,
        blend_file: Path,
        output_directory: Path,
    ) -> None:
        super().__init__()
        self._preview_service = preview_service
        self._blend_file = blend_file
        self._output_directory = output_directory
        self.signals = ModelPreviewWorkerSignals()

    @Slot()
    def run(self) -> None:
        self.signals.started.emit()
        try:
            self.signals.progress.emit("Rendering original model preview...")
            report: ModelPreviewReport = self._preview_service.generate(
                self._blend_file,
                self._output_directory,
            )
        except Exception as exc:  # noqa: BLE001 - show infrastructure failures in GUI.
            self.signals.failed.emit(str(exc))
            return
        self.signals.finished.emit(report)


class GeometryReportWorkerSignals(QObject):
    started = Signal()
    progress = Signal(str)
    finished = Signal(object)
    failed = Signal(str)


class GeometryReportWorker(QRunnable):
    def __init__(
        self,
        geometry_service: GeometryReportService,
        source_file: Path,
        output_directory: Path,
    ) -> None:
        super().__init__()
        self._geometry_service = geometry_service
        self._source_file = source_file
        self._output_directory = output_directory
        self.signals = GeometryReportWorkerSignals()

    @Slot()
    def run(self) -> None:
        self.signals.started.emit()
        try:
            self.signals.progress.emit("Analyzing geometry density in Blender...")
            report: GeometryReport = self._geometry_service.generate(
                self._source_file,
                self._output_directory,
            )
        except Exception as exc:  # noqa: BLE001 - show infrastructure failures in GUI.
            self.signals.failed.emit(str(exc))
            return
        self.signals.finished.emit(report)


class SimplificationReportWorkerSignals(QObject):
    started = Signal()
    progress = Signal(str)
    finished = Signal(object)
    failed = Signal(str)


class SimplificationReportWorker(QRunnable):
    def __init__(
        self,
        simplification_service: SimplificationReportService,
        source_blend_file: Path,
        optimized_blend_file: Path | None,
        output_directory: Path,
    ) -> None:
        super().__init__()
        self._simplification_service = simplification_service
        self._source_blend_file = source_blend_file
        self._optimized_blend_file = optimized_blend_file
        self._output_directory = output_directory
        self.signals = SimplificationReportWorkerSignals()

    @Slot()
    def run(self) -> None:
        self.signals.started.emit()
        try:
            self.signals.progress.emit("Comparing original and optimized geometry...")
            report: SimplificationReport = self._simplification_service.generate(
                self._source_blend_file,
                self._optimized_blend_file,
                self._output_directory,
            )
        except Exception as exc:  # noqa: BLE001 - show infrastructure failures in GUI.
            self.signals.failed.emit(str(exc))
            return
        self.signals.finished.emit(report)


class QemHeatmapWorkerSignals(QObject):
    started = Signal()
    progress = Signal(str)
    finished = Signal(object)
    failed = Signal(str)


class QemHeatmapWorker(QRunnable):
    def __init__(
        self,
        qem_heatmap_service: QemHeatmapService,
        source_file: Path,
        output_directory: Path,
    ) -> None:
        super().__init__()
        self._qem_heatmap_service = qem_heatmap_service
        self._source_file = source_file
        self._output_directory = output_directory
        self.signals = QemHeatmapWorkerSignals()

    @Slot()
    def run(self) -> None:
        self.signals.started.emit()
        try:
            self.signals.progress.emit("Computing QEM edge collapse costs...")
            report = self._qem_heatmap_service.generate(
                self._source_file,
                self._output_directory,
            )
        except Exception as exc:  # noqa: BLE001 - show infrastructure failures in GUI.
            self.signals.failed.emit(str(exc))
            return
        self.signals.finished.emit(report)


class ScaleAnalysisWorkerSignals(QObject):
    started = Signal()
    progress = Signal(str)
    finished = Signal(object)
    failed = Signal(str)


class ScaleAnalysisWorker(QRunnable):
    def __init__(
        self,
        scale_analysis_service: ScaleAnalysisService,
        source_file: Path,
        output_directory: Path,
    ) -> None:
        super().__init__()
        self._scale_analysis_service = scale_analysis_service
        self._source_file = source_file
        self._output_directory = output_directory
        self.signals = ScaleAnalysisWorkerSignals()

    @Slot()
    def run(self) -> None:
        self.signals.started.emit()
        try:
            self.signals.progress.emit("Computing multi-scale visual importance...")
            report = self._scale_analysis_service.generate(
                self._source_file,
                self._output_directory,
            )
        except Exception as exc:  # noqa: BLE001 - show infrastructure failures in GUI.
            self.signals.failed.emit(str(exc))
            return
        self.signals.finished.emit(report)


class AFCostCandidateWorkerSignals(QObject):
    started = Signal()
    progress = Signal(str)
    finished = Signal(object)
    failed = Signal(str)


class AFCostCandidateWorker(QRunnable):
    def __init__(
        self,
        afcost_candidate_service: AFCostCandidateService,
        source_file: Path,
        output_directory: Path,
    ) -> None:
        super().__init__()
        self._afcost_candidate_service = afcost_candidate_service
        self._source_file = source_file
        self._output_directory = output_directory
        self.signals = AFCostCandidateWorkerSignals()

    @Slot()
    def run(self) -> None:
        self.signals.started.emit()
        try:
            self.signals.progress.emit("Computing AF cost combination candidates...")
            report = self._afcost_candidate_service.generate(
                self._source_file,
                self._output_directory,
            )
        except Exception as exc:  # noqa: BLE001 - show infrastructure failures in GUI.
            self.signals.failed.emit(str(exc))
            return
        self.signals.finished.emit(report)


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
    def __init__(
        self,
        build_service: CitiesSkylinesBuildService,
        blend_file: Path,
        build_folder: Path | None = None,
        optimize: bool = False,
        target_triangle_count: int | None = None,
    ) -> None:
        super().__init__()
        self._build_service = build_service
        self._blend_file = blend_file
        self._build_folder = build_folder
        self._optimize = optimize
        self._target_triangle_count = target_triangle_count
        self.signals = CitiesSkylinesBuildWorkerSignals()

    @Slot()
    def run(self) -> None:
        self.signals.started.emit()
        try:
            self.signals.progress.emit("Building Cities Skylines asset package...")
            report: CitiesSkylinesBuildReport = self._build_service.build(
                self._blend_file,
                self._build_folder,
                self._optimize,
                self._target_triangle_count,
            )
        except Exception as exc:  # noqa: BLE001 - show infrastructure failures in GUI.
            self.signals.failed.emit(str(exc))
            return
        self.signals.finished.emit(report)
