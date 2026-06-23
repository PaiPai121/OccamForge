from __future__ import annotations

import base64
import html
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from collections.abc import Callable

from PySide6.QtCore import QObject, QSettings, QThreadPool, QTimer, QUrl, Qt, Signal, Slot
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QFileDialog, QMainWindow

from assetforge.models.analysis_dto import report_to_dict
from assetforge.models.build_dto import build_report_to_dict
from assetforge.models.geometry_report_dto import geometry_report_to_dict
from assetforge.models.model_preview_dto import model_preview_report_to_dict
from assetforge.models.preprocess_dto import preprocess_report_to_dict
from assetforge.models.real_optimization_preview_dto import real_preview_report_to_dict
from assetforge.models.simplification_report_dto import simplification_report_to_dict
from assetforge.models.validation_dto import validation_report_to_dict
from assetforge.gui.workers import (
    AFCostCandidateWorker,
    AnalysisWorker,
    CitiesSkylinesBuildWorker,
    GeometryReportWorker,
    LocalSimplificationWorker,
    ModelPreviewWorker,
    PreprocessWorker,
    QemHeatmapWorker,
    RealOptimizationPreviewWorker,
    ScaleAnalysisWorker,
    SimplificationReportWorker,
    ValidationWorker,
)
from assetforge.services.afcost_candidates import AFCostCandidateService
from assetforge.services.blender_configuration import BlenderConfigurationService
from assetforge.services.cities_skylines_build import CitiesSkylinesBuildService
from assetforge.services.geometry_report import GeometryReportService
from assetforge.services.local_simplification import LocalSimplificationService
from assetforge.services.model_preview import ModelPreviewService
from assetforge.services.preprocess import PreprocessService
from assetforge.services.qem_heatmap import QemHeatmapService
from assetforge.services.real_optimization_preview import RealOptimizationPreviewService
from assetforge.services.scale_analysis import ScaleAnalysisService
from assetforge.services.simplification_report import SimplificationReportService
from assetforge.services.vehicle_analysis import VehicleAnalysisService
from assetforge.services.vehicle_validation import VehicleValidationService


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload)


def _file_url(path: Path) -> str | None:
    if not path.exists():
        return None
    stat = path.stat()
    return f"{path.resolve().as_uri()}?v={stat.st_mtime_ns}-{stat.st_size}"


def _read_json_file(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _image_data_uri(path: Path) -> str:
    data = path.read_bytes()
    return "data:image/png;base64," + base64.b64encode(data).decode("ascii")


class AssetForgeBridge(QObject):
    stateChanged = Signal(str)
    logAdded = Signal(str)
    uiDispatch = Signal(object)

    def __init__(
        self,
        analysis_service: VehicleAnalysisService,
        validation_service: VehicleValidationService,
        build_service: CitiesSkylinesBuildService,
        preprocess_service: PreprocessService,
        real_preview_service: RealOptimizationPreviewService,
        local_simplification_service: LocalSimplificationService,
        model_preview_service: ModelPreviewService,
        geometry_report_service: GeometryReportService,
        simplification_report_service: SimplificationReportService,
        qem_heatmap_service: QemHeatmapService,
        scale_analysis_service: ScaleAnalysisService,
        afcost_candidate_service: AFCostCandidateService,
        blender_configuration: BlenderConfigurationService,
    ) -> None:
        super().__init__()
        self._analysis_service = analysis_service
        self._validation_service = validation_service
        self._build_service = build_service
        self._preprocess_service = preprocess_service
        self._real_preview_service = real_preview_service
        self._local_simplification_service = local_simplification_service
        self._model_preview_service = model_preview_service
        self._geometry_report_service = geometry_report_service
        self._simplification_report_service = simplification_report_service
        self._qem_heatmap_service = qem_heatmap_service
        self._scale_analysis_service = scale_analysis_service
        self._afcost_candidate_service = afcost_candidate_service
        self._blender_configuration = blender_configuration
        self._thread_pool = QThreadPool.globalInstance()
        self._active_workers: list[object] = []
        self._selected_file: Path | None = None
        self._current_preview_target: int | None = None
        self._current_preview_blend_file: Path | None = None
        self._preprocessed_file: Path | None = None
        self._busy = False
        self._analysis_generation = 0
        self._source_preview_generation = 0
        self._settings = QSettings("AssetForge", "AssetForge")
        output_folder, output_source = self._default_output_folder()
        target_triangles = self._saved_target_triangles()
        self.uiDispatch.connect(
            self._execute_ui_callback,
            Qt.ConnectionType.QueuedConnection,
        )
        self._state: dict[str, Any] = {
            "selectedFile": None,
            "targetTriangles": target_triangles,
            "optimizeEnabled": True,
            "busy": False,
            "sourcePreviewBusy": False,
            "status": "Choose a Blender vehicle file",
            "analysis": None,
            "validation": None,
            "sourcePreview": None,
            "preprocess": None,
            "realPreview": None,
            "geometryReport": None,
            "simplificationReport": None,
            "qemHeatmap": None,
            "scaleAnalysis": None,
            "afcostCandidates": None,
            "build": None,
            "currentPreviewTarget": None,
            "outputFolder": str(output_folder) if output_folder else None,
            "outputFolderSource": output_source,
        }

    @Slot(result=str)
    def initialState(self) -> str:
        self._debug_log("backend: initial state requested")
        return _json(self._state)

    @Slot(str)
    def debugLog(self, message: str) -> None:
        self._debug_log(f"frontend: {message}")
        if (
            os.getenv("ASSETFORGE_AUTOTEST_EXIT_ON_FIRST_FRAME") == "1"
            and "first viewport frame drawn" in message
        ):
            self._debug_log("backend: autotest first frame observed; waiting for workers before exit")
            QTimer.singleShot(0, self._quit_autotest_when_idle)

    def _quit_autotest_when_idle(self) -> None:
        if self._active_workers:
            QTimer.singleShot(250, self._quit_autotest_when_idle)
            return
        self._debug_log("backend: autotest workers idle; exiting")
        app = QApplication.instance()
        if app is not None:
            app.quit()

    @Slot(str, result=str)
    def loadPreviewMesh(self, mesh_path_value: str) -> str:
        mesh_path = Path(mesh_path_value)
        self._debug_log(f"backend: loadPreviewMesh requested: {mesh_path}")
        if not mesh_path.exists():
            self._debug_log("backend: loadPreviewMesh failed, file does not exist")
            return ""
        mesh_size = mesh_path.stat().st_size
        self._debug_log(f"backend: loadPreviewMesh file size={mesh_size:,} bytes")
        if mesh_size > 25 * 1024 * 1024:
            self._debug_log("backend: loadPreviewMesh rejected, file too large")
            return ""
        try:
            text = mesh_path.read_text(encoding="utf-8")
        except OSError as exc:
            self._debug_log(f"backend: loadPreviewMesh failed: {exc}")
            return ""
        self._debug_log(f"backend: loadPreviewMesh returning {len(text):,} chars")
        return text

    @Slot(bool, result=str)
    def exportHeatmapComparison(self, inverted: bool) -> str:
        qem = self._state.get("qemHeatmap") or {}
        scale = self._state.get("scaleAnalysis") or {}
        if not qem or not scale:
            return _json({"errors": ["Generate Heatmap Diagnostics before exporting."]})

        mode = "inverse" if inverted else "normal"
        definitions = [
            (
                "Classic QEM cost",
                qem.get("heatmap_inverse_png" if inverted else "heatmap_png"),
                "Low cost" if not inverted else "High cost",
                "High cost" if not inverted else "Low cost",
            ),
            (
                "Feature-Aware QEM cost",
                qem.get("feature_heatmap_inverse_png" if inverted else "feature_heatmap_png"),
                "Low cost" if not inverted else "High cost",
                "High cost" if not inverted else "Low cost",
            ),
            (
                "Normal variation H",
                scale.get("mean_curvature_heatmap_inverse" if inverted else "mean_curvature_heatmap"),
                "Low variation" if not inverted else "High variation",
                "High variation" if not inverted else "Low variation",
            ),
            (
                "Center-surround response",
                scale.get("center_surround_heatmap_inverse" if inverted else "center_surround_heatmap"),
                "Similar to surround" if not inverted else "Different from surround",
                "Different from surround" if not inverted else "Similar to surround",
            ),
            (
                "Scale persistence",
                scale.get("scale_persistence_heatmap_inverse" if inverted else "scale_persistence_heatmap"),
                "Low persistence" if not inverted else "High persistence",
                "High persistence" if not inverted else "Low persistence",
            ),
            (
                "Tiny detail score",
                scale.get("tiny_detail_heatmap_inverse" if inverted else "tiny_detail_heatmap"),
                "Not tiny detail" if not inverted else "Likely removable",
                "Likely removable" if not inverted else "Not tiny detail",
            ),
        ]
        missing = [title for title, path_value, *_ in definitions if not path_value or not Path(str(path_value)).exists()]
        if missing:
            return _json({"errors": [f"Missing heatmap images: {', '.join(missing)}"]})

        output_root = (self._selected_file.parent if self._selected_file else Path.cwd()) / "heatmap_exports"
        output_root.mkdir(parents=True, exist_ok=True)
        output_path = output_root / f"heatmap_comparison_{mode}.svg"
        title = f"Heatmap Diagnostics Comparison ({mode})"
        generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        image_width = 1040
        image_height = 742
        card_width = 1120
        card_height = 900
        gap = 40
        margin = 60
        header_height = 110
        svg_width = margin * 2 + card_width * 2 + gap
        svg_height = margin + header_height + card_height * 3 + gap * 2 + 50

        cards: list[str] = []
        for index, (name, path_value, low_label, high_label) in enumerate(definitions):
            row = index // 2
            col = index % 2
            x = margin + col * (card_width + gap)
            y = margin + header_height + row * (card_height + gap)
            image_uri = _image_data_uri(Path(str(path_value)))
            cards.append(
                f"""
  <g transform="translate({x},{y})">
    <rect width="{card_width}" height="{card_height}" rx="18" fill="#ffffff" stroke="#d7dee8"/>
    <text x="28" y="48" font-size="28" font-weight="700" fill="#18202b">{html.escape(name)}</text>
    <image x="28" y="72" width="{image_width}" height="{image_height}" preserveAspectRatio="xMidYMid meet" href="{image_uri}"/>
    <text x="28" y="852" font-size="20" font-weight="700" fill="#667085">{html.escape(low_label)}</text>
    <rect x="260" y="836" width="600" height="20" rx="10" fill="url(#heatmapGradient)"/>
    <text x="1068" y="852" text-anchor="end" font-size="20" font-weight="700" fill="#667085">{html.escape(high_label)}</text>
  </g>"""
            )

        svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{svg_width}" height="{svg_height}" viewBox="0 0 {svg_width} {svg_height}">
  <defs>
    <linearGradient id="heatmapGradient" x1="0%" x2="100%" y1="0%" y2="0%">
      <stop offset="0%" stop-color="#051cff"/>
      <stop offset="32%" stop-color="#00bff0"/>
      <stop offset="52%" stop-color="#39d353"/>
      <stop offset="74%" stop-color="#ffd21a"/>
      <stop offset="100%" stop-color="#e51518"/>
    </linearGradient>
  </defs>
  <rect width="100%" height="100%" fill="#edf1f5"/>
  <text x="{margin}" y="{margin + 36}" font-size="38" font-weight="800" fill="#18202b">{html.escape(title)}</text>
  <text x="{margin}" y="{margin + 74}" font-size="22" fill="#667085">Source: {html.escape(str(self._selected_file or 'unknown'))} | Generated: {html.escape(generated_at)}</text>
  {''.join(cards)}
</svg>
"""
        output_path.write_text(svg, encoding="utf-8")
        payload = {
            "path": str(output_path),
            "url": _file_url(output_path),
            "mode": mode,
            "errors": [],
        }
        self.logAdded.emit(f"Exported heatmap comparison: {output_path}")
        return _json(payload)

    @Slot(result=str)
    def exportAFCostCandidates(self) -> str:
        report = self._state.get("afcostCandidates") or {}
        candidates = report.get("candidates") or []
        if not candidates:
            return _json({"errors": ["Generate AF cost candidates before exporting."]})
        missing = [
            str(candidate.get("name", "candidate"))
            for candidate in candidates
            if not candidate.get("heatmap_png") or not Path(str(candidate.get("heatmap_png"))).exists()
        ]
        if missing:
            return _json({"errors": [f"Missing candidate images: {', '.join(missing)}"]})

        output_root = (self._selected_file.parent if self._selected_file else Path.cwd()) / "heatmap_exports"
        output_root.mkdir(parents=True, exist_ok=True)
        output_path = output_root / "afcost_candidates_comparison.svg"
        card_width = 640
        card_height = 560
        image_width = 584
        image_height = 418
        gap = 30
        margin = 50
        header_height = 116
        columns = 3
        rows = (len(candidates) + columns - 1) // columns
        svg_width = margin * 2 + card_width * columns + gap * (columns - 1)
        svg_height = margin + header_height + card_height * rows + gap * max(0, rows - 1) + 40
        generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cards: list[str] = []
        for index, candidate in enumerate(candidates):
            row = index // columns
            col = index % columns
            x = margin + col * (card_width + gap)
            y = margin + header_height + row * (card_height + gap)
            name = str(candidate.get("name", "-"))
            formula = str(candidate.get("formula", ""))
            image_uri = _image_data_uri(Path(str(candidate.get("heatmap_png"))))
            cards.append(
                f"""
  <g transform="translate({x},{y})">
    <rect width="{card_width}" height="{card_height}" rx="16" fill="#ffffff" stroke="#d7dee8"/>
    <text x="24" y="42" font-size="24" font-weight="800" fill="#18202b">{html.escape(name)}</text>
    <text x="24" y="72" font-size="15" font-weight="700" fill="#667085">{html.escape(formula)}</text>
    <image x="24" y="92" width="{image_width}" height="{image_height}" preserveAspectRatio="xMidYMid meet" href="{image_uri}"/>
    <text x="24" y="535" font-size="16" font-weight="700" fill="#667085">Low combo score</text>
    <rect x="210" y="522" width="250" height="16" rx="8" fill="url(#heatmapGradient)"/>
    <text x="608" y="535" text-anchor="end" font-size="16" font-weight="700" fill="#667085">High combo score</text>
  </g>"""
            )
        svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{svg_width}" height="{svg_height}" viewBox="0 0 {svg_width} {svg_height}">
  <defs>
    <linearGradient id="heatmapGradient" x1="0%" x2="100%" y1="0%" y2="0%">
      <stop offset="0%" stop-color="#051cff"/>
      <stop offset="32%" stop-color="#00bff0"/>
      <stop offset="52%" stop-color="#39d353"/>
      <stop offset="74%" stop-color="#ffd21a"/>
      <stop offset="100%" stop-color="#e51518"/>
    </linearGradient>
  </defs>
  <rect width="100%" height="100%" fill="#edf1f5"/>
  <text x="{margin}" y="{margin + 36}" font-size="38" font-weight="800" fill="#18202b">AF Cost Candidate Comparison</text>
  <text x="{margin}" y="{margin + 74}" font-size="20" fill="#667085">Source: {html.escape(str(self._selected_file or 'unknown'))} | Generated: {html.escape(generated_at)}</text>
  {''.join(cards)}
</svg>
"""
        output_path.write_text(svg, encoding="utf-8")
        self.logAdded.emit(f"Exported AF cost candidate comparison: {output_path}")
        return _json({"path": str(output_path), "url": _file_url(output_path), "errors": []})

    @Slot(int)
    def setTargetTriangles(self, target_triangles: int) -> None:
        if target_triangles <= 0:
            return
        target_triangles = int(target_triangles)
        previous_target = int(self._state.get("targetTriangles") or 0)
        if previous_target == target_triangles:
            return
        self._settings.setValue("targetTriangles", target_triangles)
        self._state["targetTriangles"] = target_triangles
        if self._current_preview_target is not None and self._current_preview_target != target_triangles:
            self._current_preview_target = None
            self._current_preview_blend_file = None
            self._state["currentPreviewTarget"] = None
            self._state["realPreview"] = None
            self._state["simplificationReport"] = None
            self._state["status"] = "Target changed. Review Stage 1 before optimizing again."
        self._emit_state()

    @Slot(result=str)
    def selectBlendFile(self) -> str:
        path, _ = QFileDialog.getOpenFileName(
            None,
            "Select Model File",
            self._last_directory("lastBlendDirectory"),
            "Model Files (*.blend *.obj *.fbx *.glb *.gltf)",
        )
        if path:
            self.openBlendFile(path)
        return _json(self._state)

    @Slot(str, result=str)
    def openBlendFile(self, path: str) -> str:
        model_file = Path(path)
        supported = {".blend", ".obj", ".fbx", ".glb", ".gltf"}
        if not model_file.exists() or model_file.suffix.lower() not in supported:
            self._fail(f"Expected an existing model file, got: {model_file}")
            return _json(self._state)
        self._selected_file = model_file
        self._settings.setValue("lastBlendDirectory", str(self._selected_file.parent))
        self._state.update(
            {
                "selectedFile": str(self._selected_file),
                "analysis": None,
                "validation": None,
                "sourcePreview": None,
                "sourcePreviewBusy": False,
                "preprocess": None,
                "realPreview": None,
                "geometryReport": None,
                "simplificationReport": None,
                "qemHeatmap": None,
                "scaleAnalysis": None,
                "afcostCandidates": None,
                "build": None,
                "currentPreviewTarget": None,
                "status": "Loading original model preview..."
                if self._selected_file.suffix.lower() == ".blend"
                else "Model selected. Current model analysis is available.",
            }
        )
        self._current_preview_target = None
        self._current_preview_blend_file = None
        self._preprocessed_file = None
        self._emit_state()
        self.logAdded.emit(f"Selected file: {self._selected_file}")
        self._debug_log(f"backend: selected file {self._selected_file}")
        if self._selected_file.suffix.lower() == ".blend":
            self._analysis_generation += 1
            generation = self._analysis_generation
            QTimer.singleShot(
                0,
                lambda: self._auto_analyze_selected_file(generation),
            )
        return _json(self._state)

    @Slot(result=str)
    def browseBlender(self) -> str:
        path, _ = QFileDialog.getOpenFileName(
            None,
            "Select blender.exe",
            self._last_directory("lastBlenderDirectory"),
            "Blender Executable (blender.exe)",
        )
        if path:
            self._settings.setValue("lastBlenderDirectory", str(Path(path).parent))
            try:
                result = self._blender_configuration.save_manual_path(Path(path))
            except ValueError as exc:
                self._fail(str(exc))
            else:
                self._state["status"] = "Blender configured"
                self._emit_state()
                self.logAdded.emit(f"Blender configured from {result.source}: {result.executable}")
        return _json(self._state)

    @Slot(result=str)
    def browseOutputFolder(self) -> str:
        path = QFileDialog.getExistingDirectory(
            None,
            "Select Cities Skylines Import Folder",
            str(self._current_output_folder() or Path.home()),
        )
        if path:
            output_folder = Path(path)
            self._settings.setValue("lastOutputFolder", str(output_folder))
            self._state["outputFolder"] = str(output_folder)
            self._state["outputFolderSource"] = "manual"
            self._emit_state()
            self.logAdded.emit(f"Output folder configured: {output_folder}")
            self._debug_log(f"backend: output folder configured manually: {output_folder}")
        return _json(self._state)

    @Slot()
    def analyze(self) -> None:
        if not self._selected_file:
            self.logAdded.emit("Select a .blend file before analyzing.")
            return
        if self._selected_file.suffix.lower() != ".blend":
            self.logAdded.emit("Model structure analysis currently requires a .blend file.")
            return
        self._analysis_generation += 1
        self._begin_analysis("Analyzing vehicle structure...", "Analysis started.")

    @Slot()
    def analyzePipelineFile(self) -> None:
        if not self._selected_file:
            self.logAdded.emit("Select a .blend file before refreshing the preview.")
            return
        if self._selected_file.suffix.lower() != ".blend":
            self.logAdded.emit("Pipeline preview currently requires a .blend file.")
            return
        self._analysis_generation += 1
        self._begin_analysis(
            "Updating preview from cleaned model...",
            "Refreshing preview from the current pipeline model.",
            self._pipeline_blend_file(),
        )

    def _auto_analyze_selected_file(self, generation: int) -> None:
        if generation != self._analysis_generation:
            return
        self._begin_analysis(
            "Loading original model preview...",
            "Opening Blender in the background to read the original model.",
        )

    def _begin_analysis(
        self,
        status: str,
        started_log: str,
        blend_file: Path | None = None,
    ) -> None:
        target_file = blend_file or self._selected_file
        if not target_file:
            return
        if self._start_busy(status):
            return
        self._debug_log(f"backend: analysis worker queued for {target_file}")
        worker = AnalysisWorker(self._analysis_service, target_file)
        worker.signals.started.connect(
            lambda: self._run_on_ui(
                lambda: (
                    self.logAdded.emit(started_log),
                    self._debug_log("backend: analysis worker started"),
                )
            )
        )
        worker.signals.finished.connect(
            lambda report: self._run_on_ui(lambda: self._analysis_finished(report))
        )
        worker.signals.failed.connect(
            lambda message: self._run_on_ui(lambda: self._fail(message))
        )
        self._start_worker(worker)

    @Slot()
    def renderSourcePreview(self) -> None:
        if not self._selected_file:
            self.logAdded.emit("Select a .blend file before rendering a source preview.")
            return
        if self._selected_file.suffix.lower() != ".blend":
            self.logAdded.emit("Viewport preview currently requires a .blend file.")
            return
        self._source_preview_generation += 1
        generation = self._source_preview_generation
        self._state["sourcePreviewBusy"] = True
        self._state["status"] = "File selected. Rendering original model preview..."
        self._emit_state()
        self.logAdded.emit("Rendering original model preview...")
        worker = ModelPreviewWorker(
            self._model_preview_service,
            self._selected_file,
            self._selected_file.parent / "previews",
        )
        worker.signals.started.connect(
            lambda: self._run_on_ui(lambda: self.logAdded.emit("Original preview started."))
        )
        worker.signals.progress.connect(lambda message: self._run_on_ui(lambda: self._progress(message)))
        worker.signals.finished.connect(
            lambda report: self._run_on_ui(lambda: self._source_preview_finished(report))
        )
        worker.signals.failed.connect(
            lambda message: self._run_on_ui(lambda: self._source_preview_failed(message))
        )
        self._start_worker(worker)
        QTimer.singleShot(
            45000,
            lambda: self._source_preview_timeout(generation),
        )

    @Slot(int, int)
    def generateRealPreview(self, target_triangles: int, pipeline_stage: int = 1) -> None:
        if not self._selected_file:
            self.logAdded.emit("Select a .blend file before generating a preview.")
            return
        if self._selected_file.suffix.lower() != ".blend":
            self.logAdded.emit("Optimization preview currently requires a .blend file.")
            return
        if target_triangles <= 0:
            self.logAdded.emit("Target triangles must be greater than zero.")
            return
        if pipeline_stage not in {1, 2, 3}:
            self.logAdded.emit("Optimization pipeline stage must be Stage 1, Stage 2, or Stage 3.")
            return
        if self._start_busy("Generating real optimization preview..."):
            return
        self._state["targetTriangles"] = target_triangles
        self._settings.setValue("targetTriangles", target_triangles)
        self._state["realPreview"] = None
        self._state["currentPreviewTarget"] = None
        self._current_preview_target = None
        self._current_preview_blend_file = None
        worker = RealOptimizationPreviewWorker(
            self._real_preview_service,
            self._pipeline_blend_file(),
            "cities_skylines_vehicle",
            target_triangles,
            self._selected_file.parent / "previews",
            pipeline_stage,
        )
        worker.signals.started.connect(
            lambda: self._run_on_ui(lambda: self.logAdded.emit("Real preview started."))
        )
        worker.signals.progress.connect(lambda message: self._run_on_ui(lambda: self._progress(message)))
        worker.signals.finished.connect(
            lambda report: self._run_on_ui(lambda: self._real_preview_finished(report))
        )
        worker.signals.failed.connect(lambda message: self._run_on_ui(lambda: self._fail(message)))
        self._start_worker(worker)

    @Slot(int)
    @Slot(int, str)
    def generateLocalSimplification(self, target_triangles: int, combo_candidate: str = "auto") -> None:
        if not self._selected_file:
            self.logAdded.emit("Select a .blend file before generating local simplification.")
            return
        if self._selected_file.suffix.lower() != ".blend":
            self.logAdded.emit("Local simplification currently requires a .blend file.")
            return
        if target_triangles <= 0:
            self.logAdded.emit("Target triangles must be greater than zero.")
            return
        if not self._state.get("qemHeatmap"):
            self.logAdded.emit("Generate QEM heatmap before local simplification.")
            return
        if not self._state.get("afcostCandidates"):
            self.logAdded.emit("Generate combo scores before local simplification.")
            return
        if self._start_busy("Running local edge-collapse simplification..."):
            return
        self._state["targetTriangles"] = target_triangles
        self._settings.setValue("targetTriangles", target_triangles)
        self._state["realPreview"] = None
        self._state["currentPreviewTarget"] = None
        self._current_preview_target = None
        self._current_preview_blend_file = None
        worker = LocalSimplificationWorker(
            self._local_simplification_service,
            self._pipeline_blend_file(),
            "cities_skylines_vehicle",
            target_triangles,
            self._selected_file.parent / "previews",
            combo_candidate or "auto",
        )
        worker.signals.started.connect(
            lambda: self._run_on_ui(
                lambda: self.logAdded.emit(
                    f"Local simplification started with {combo_candidate or 'auto'}."
                )
            )
        )
        worker.signals.progress.connect(lambda message: self._run_on_ui(lambda: self._progress(message)))
        worker.signals.finished.connect(
            lambda report: self._run_on_ui(lambda: self._real_preview_finished(report))
        )
        worker.signals.failed.connect(lambda message: self._run_on_ui(lambda: self._fail(message)))
        self._start_worker(worker)

    @Slot()
    def applyCurrentPreview(self) -> None:
        if self._current_preview_target is None:
            return
        self._state["targetTriangles"] = self._current_preview_target
        self._settings.setValue("targetTriangles", self._current_preview_target)
        self._state["optimizeEnabled"] = True
        self._state["status"] = f"Selected {self._current_preview_target:,} tris as build target"
        self._emit_state()

    @Slot()
    def preprocess(self) -> None:
        if not self._selected_file:
            self.logAdded.emit("Select a .blend file before preprocessing.")
            return
        if self._selected_file.suffix.lower() != ".blend":
            self.logAdded.emit("Safe preprocess currently requires a .blend file.")
            return
        if self._start_busy("Running safe preprocess..."):
            return
        worker = PreprocessWorker(self._preprocess_service, self._selected_file, 1.0)
        worker.signals.started.connect(
            lambda: self._run_on_ui(lambda: self.logAdded.emit("Safe preprocess started."))
        )
        worker.signals.progress.connect(lambda message: self._run_on_ui(lambda: self._progress(message)))
        worker.signals.finished.connect(
            lambda report: self._run_on_ui(lambda: self._preprocess_finished(report))
        )
        worker.signals.failed.connect(lambda message: self._run_on_ui(lambda: self._fail(message)))
        self._start_worker(worker)

    @Slot(bool)
    def setOptimizeEnabled(self, enabled: bool) -> None:
        self._state["optimizeEnabled"] = enabled

    @Slot()
    def validate(self) -> None:
        if not self._selected_file:
            return
        if self._selected_file.suffix.lower() != ".blend":
            self.logAdded.emit("Validation currently requires a .blend file.")
            return
        if self._start_busy("Validating asset readiness..."):
            return
        worker = ValidationWorker(
            self._validation_service,
            self._selected_file,
            "cities_skylines_vehicle",
        )
        worker.signals.started.connect(
            lambda: self._run_on_ui(lambda: self.logAdded.emit("Validation started."))
        )
        worker.signals.progress.connect(lambda message: self._run_on_ui(lambda: self._progress(message)))
        worker.signals.finished.connect(
            lambda report: self._run_on_ui(lambda: self._validation_finished(report))
        )
        worker.signals.failed.connect(lambda message: self._run_on_ui(lambda: self._fail(message)))
        self._start_worker(worker)

    @Slot()
    def generateGeometryReport(self) -> None:
        if not self._selected_file:
            self.logAdded.emit("Select a model file before generating a geometry report.")
            return
        if self._start_busy("Generating geometry report..."):
            return
        self._state["realPreview"] = None
        self._state["currentPreviewTarget"] = None
        self._current_preview_target = None
        self._current_preview_blend_file = None
        source_file = self._pipeline_blend_file()
        worker = GeometryReportWorker(
            self._geometry_report_service,
            source_file,
            self._selected_file.parent / "geometry_reports",
        )
        worker.signals.started.connect(
            lambda: self._run_on_ui(
                lambda: self.logAdded.emit(f"Geometry report started for {source_file.name}.")
            )
        )
        worker.signals.progress.connect(lambda message: self._run_on_ui(lambda: self._progress(message)))
        worker.signals.finished.connect(
            lambda report: self._run_on_ui(lambda: self._geometry_report_finished(report))
        )
        worker.signals.failed.connect(lambda message: self._run_on_ui(lambda: self._fail(message)))
        self._start_worker(worker)

    @Slot()
    def generateSimplificationReport(self) -> None:
        if not self._selected_file:
            self.logAdded.emit("Select a .blend file before generating a simplification report.")
            return
        if self._selected_file.suffix.lower() != ".blend":
            self.logAdded.emit("Simplification analysis currently requires a .blend file.")
            return
        optimized_blend_file = self._current_preview_blend_file
        if optimized_blend_file is None or not optimized_blend_file.exists():
            self.logAdded.emit("Generate a triangle reduction preview before comparing reduction.")
            self._state["status"] = "Generate a reduction preview before comparing"
            self._emit_state()
            return
        if self._start_busy("Generating simplification analysis..."):
            return
        worker = SimplificationReportWorker(
            self._simplification_report_service,
            self._pipeline_blend_file(),
            optimized_blend_file,
            self._selected_file.parent / "simplification_reports",
        )
        worker.signals.started.connect(
            lambda: self._run_on_ui(
                lambda: self.logAdded.emit(
                    f"Simplification analysis started for {optimized_blend_file.name}."
                )
            )
        )
        worker.signals.progress.connect(lambda message: self._run_on_ui(lambda: self._progress(message)))
        worker.signals.finished.connect(
            lambda report: self._run_on_ui(lambda: self._simplification_report_finished(report))
        )
        worker.signals.failed.connect(lambda message: self._run_on_ui(lambda: self._fail(message)))
        self._start_worker(worker)

    @Slot()
    def generateQemHeatmap(self) -> None:
        if not self._selected_file:
            self.logAdded.emit("Select a model file before generating a QEM cost heatmap.")
            return
        if self._start_busy("Computing QEM edge cost heatmap..."):
            return
        source_file = self._pipeline_blend_file()
        worker = QemHeatmapWorker(
            self._qem_heatmap_service,
            source_file,
            self._selected_file.parent / "qem_heatmaps",
        )
        worker.signals.started.connect(
            lambda: self._run_on_ui(
                lambda: self.logAdded.emit(f"QEM heatmap started for {source_file.name}.")
            )
        )
        worker.signals.progress.connect(lambda message: self._run_on_ui(lambda: self._progress(message)))
        worker.signals.finished.connect(
            lambda report: self._run_on_ui(lambda: self._qem_heatmap_finished(report))
        )
        worker.signals.failed.connect(lambda message: self._run_on_ui(lambda: self._fail(message)))
        self._start_worker(worker)

    @Slot()
    def generateScaleAnalysis(self) -> None:
        if not self._selected_file:
            self.logAdded.emit("Select a model file before running Scale Analysis.")
            return
        if self._start_busy("Computing scale analysis heatmaps..."):
            return
        source_file = self._pipeline_blend_file()
        worker = ScaleAnalysisWorker(
            self._scale_analysis_service,
            source_file,
            self._selected_file.parent / "scale_analysis",
        )
        worker.signals.started.connect(
            lambda: self._run_on_ui(
                lambda: self.logAdded.emit(f"Scale Analysis started for {source_file.name}.")
            )
        )
        worker.signals.progress.connect(lambda message: self._run_on_ui(lambda: self._progress(message)))
        worker.signals.finished.connect(
            lambda report: self._run_on_ui(lambda: self._scale_analysis_finished(report))
        )
        worker.signals.failed.connect(lambda message: self._run_on_ui(lambda: self._fail(message)))
        self._start_worker(worker)

    @Slot()
    def generateAFCostCandidates(self) -> None:
        if not self._selected_file:
            self.logAdded.emit("Select a model file before generating AF cost candidates.")
            return
        if self._start_busy("Computing AF cost candidate heatmaps..."):
            return
        source_file = self._pipeline_blend_file()
        worker = AFCostCandidateWorker(
            self._afcost_candidate_service,
            source_file,
            self._selected_file.parent / "afcost_candidates",
        )
        worker.signals.started.connect(
            lambda: self._run_on_ui(
                lambda: self.logAdded.emit(f"AF cost candidates started for {source_file.name}.")
            )
        )
        worker.signals.progress.connect(lambda message: self._run_on_ui(lambda: self._progress(message)))
        worker.signals.finished.connect(
            lambda report: self._run_on_ui(lambda: self._afcost_candidates_finished(report))
        )
        worker.signals.failed.connect(lambda message: self._run_on_ui(lambda: self._fail(message)))
        self._start_worker(worker)

    @Slot(int, bool)
    def buildCitiesSkylinesAsset(self, target_triangles: int, optimize: bool) -> None:
        if not self._selected_file:
            self.logAdded.emit("Select a .blend file before building.")
            return
        if self._selected_file.suffix.lower() != ".blend":
            self.logAdded.emit("Cities Skylines build currently requires a .blend file.")
            return
        if target_triangles <= 0:
            self.logAdded.emit("Target triangles must be greater than zero.")
            return
        self._state["targetTriangles"] = target_triangles
        self._settings.setValue("targetTriangles", target_triangles)
        self._state["optimizeEnabled"] = optimize
        if self._start_busy("Building Cities Skylines package..."):
            return
        build_source_file = (
            self._current_preview_blend_file
            if optimize and self._current_preview_blend_file is not None and self._current_preview_blend_file.exists()
            else self._pipeline_blend_file()
        )
        worker = CitiesSkylinesBuildWorker(
            self._build_service,
            build_source_file,
            self._current_output_folder(),
            False if build_source_file == self._current_preview_blend_file else optimize,
            target_triangles,
        )
        worker.signals.started.connect(
            lambda: self._run_on_ui(lambda: self.logAdded.emit("Build started."))
        )
        worker.signals.progress.connect(lambda message: self._run_on_ui(lambda: self._progress(message)))
        worker.signals.finished.connect(
            lambda report: self._run_on_ui(lambda: self._build_finished(report))
        )
        worker.signals.failed.connect(lambda message: self._run_on_ui(lambda: self._fail(message)))
        self._start_worker(worker)

    def _start_worker(self, worker: object) -> None:
        self._active_workers.append(worker)

        def release(*_args: object) -> None:
            if worker in self._active_workers:
                self._active_workers.remove(worker)

        worker.signals.finished.connect(release)
        worker.signals.failed.connect(release)
        self._thread_pool.start(worker)

    def _analysis_finished(self, report: object) -> None:
        payload = report_to_dict(report)
        self._debug_log("backend: analysis worker finished; preparing viewport metadata")
        mesh_path = (
            Path(payload["preview_mesh_path"])
            if payload.get("preview_mesh_path")
            else None
        )
        payload["preview_mesh_url"] = (
            mesh_path.resolve().as_uri() if mesh_path and mesh_path.exists() else None
        )
        self._log_preview_mesh_metadata(mesh_path)
        self._state["analysis"] = payload
        self._debug_log(
            "backend: emitting analysis state "
            f"triangles={payload['triangle_count']:,}, "
            f"mesh_path={payload['preview_mesh_path'] or 'none'}, "
            f"mesh_url={payload['preview_mesh_url'] or 'none'}"
        )
        self._finish_busy("Analysis complete" if not payload["errors"] else "Analysis found issues")
        self.logAdded.emit(
            f"Analysis: {payload['triangle_count']:,} triangles, "
            f"{payload['wheel_count']} wheels, {payload['object_count']} objects"
        )

    def _log_preview_mesh_metadata(self, mesh_path: Path | None) -> None:
        if mesh_path is None or not mesh_path.exists():
            self._debug_log("backend: viewport mesh file was not generated")
            return
        mesh_size = mesh_path.stat().st_size
        self._debug_log(f"backend: viewport mesh file exists: {mesh_path} ({mesh_size:,} bytes)")

    def _source_preview_finished(self, report: object) -> None:
        payload = model_preview_report_to_dict(report)
        image_path = Path(payload["preview_image_path"])
        payload["preview_image_url"] = _file_url(image_path)
        self._state["sourcePreview"] = payload
        self._state["sourcePreviewBusy"] = False
        self._state["status"] = (
            "Original model preview ready" if not payload["errors"] else "Preview found issues"
        )
        self._emit_state()
        self.logAdded.emit(f"Original preview: {payload['triangle_count']:,} triangles")

    def _source_preview_failed(self, message: str) -> None:
        self._state["sourcePreviewBusy"] = False
        self._state["status"] = "Original preview failed; analysis is still available"
        self._emit_state()
        self.logAdded.emit(f"PREVIEW ERROR: {message}")

    def _source_preview_timeout(self, generation: int) -> None:
        if generation != self._source_preview_generation:
            return
        if not self._state.get("sourcePreviewBusy"):
            return
        self._state["sourcePreviewBusy"] = False
        self._state["status"] = "Original preview is still running; you can continue analyzing"
        self._emit_state()
        self.logAdded.emit("Original preview is taking longer than expected; continuing is safe.")

    def _real_preview_finished(self, report: object) -> None:
        payload = real_preview_report_to_dict(report)
        output_directory = Path(payload["output_directory"])
        for item in payload["items"]:
            image_path = Path(item["preview_image_path"])
            item["preview_image_url"] = _file_url(image_path)
            advanced_ran = any(
                str(line).startswith("Stage 2 ") or str(line).startswith("Stage 3 ")
                for line in item.get("warnings", [])
            )
            item["stage_debug"] = self._stage_debug_items(output_directory, image_path) if advanced_ran else []
        self._state["realPreview"] = payload
        if payload["items"] and not payload["items"][0]["errors"]:
            self._current_preview_target = int(payload["items"][0]["target_triangles"])
            self._state["currentPreviewTarget"] = self._current_preview_target
            self._current_preview_blend_file = Path(payload["items"][0]["preview_blend_path"])
        self._finish_busy("Real preview complete" if not payload["errors"] else "Real preview issues found")
        if payload["items"]:
            item = payload["items"][0]
            self.logAdded.emit(
                f"Preview: target {item['target_triangles']:,}, actual "
                f"{item['actual_triangles']:,}, reduction {item['reduction_percent']:.2f}%"
            )

    def _stage_debug_items(self, output_directory: Path, final_preview_image: Path) -> list[dict[str, Any]]:
        stage3_definition = (
            "3",
            "Detail Suppression",
            output_directory / "stage_3_model_preview.png",
            output_directory / "stage_3_report.json",
        )
        final_definition = (
            "Final",
            "Final Preview",
            final_preview_image,
            None,
        )
        stage2_definitions = [
            (
                "2A",
                "Input: Protection Expansion",
                output_directory / "stage_2a_protection_map.png",
                output_directory / "stage_2a_protection_report.json",
            ),
            (
                "2B",
                "Input: Detail Candidates",
                output_directory / "stage_2b_deleted_features_map.png",
                output_directory / "stage_2b_deleted_features_report.json",
            ),
            (
                "2C",
                "Input: Controlled Reduce",
                output_directory / "stage_2c_model_preview.png",
                output_directory / "stage_2c_bucket_report.json",
            ),
            (
                "2C Heatmap",
                "Input: Reduction Buckets",
                output_directory / "stage_2c_bucket_heatmap.png",
                output_directory / "stage_2c_bucket_report.json",
            ),
            (
                "2D",
                "Input: Local Fallback",
                output_directory / "stage_2d_model_preview.png",
                output_directory / "stage_2d_report.json",
            ),
        ]
        definitions = (
            [stage3_definition, final_definition, *stage2_definitions]
            if (output_directory / "stage_3_report.json").exists()
            else [*stage2_definitions, final_definition]
        )
        items: list[dict[str, Any]] = []
        for stage_id, title, image_path, report_path in definitions:
            report = _read_json_file(report_path)
            if not image_path.exists() and report is None:
                continue
            items.append(
                {
                    "stage_id": stage_id,
                    "title": title,
                    "image_path": str(image_path) if image_path.exists() else None,
                    "image_url": _file_url(image_path),
                    "report_path": str(report_path) if report_path and report_path.exists() else None,
                    "report": report,
                }
            )
        return items

    def _validation_finished(self, report: object) -> None:
        payload = validation_report_to_dict(report)
        self._state["validation"] = payload
        self._finish_busy(f"Validation complete: {payload['rating']}")
        self.logAdded.emit(f"Validation score: {payload['score']} ({payload['rating']})")

    def _geometry_report_finished(self, report: object) -> None:
        payload = geometry_report_to_dict(report)
        image_path = Path(payload["heatmap_image_path"])
        payload["heatmap_image_url"] = _file_url(image_path)
        self._state["geometryReport"] = payload
        status = "Geometry report complete" if not payload["errors"] else "Geometry report found issues"
        self._finish_busy(status)
        self.logAdded.emit(
            "Geometry report: "
            f"{payload['overall']['triangles']:,} triangles, "
            f"{len(payload['dense_regions'])} dense regions"
        )

    def _preprocess_finished(self, report: object) -> None:
        payload = preprocess_report_to_dict(report)
        self._state["preprocess"] = payload
        if not payload["errors"]:
            self._preprocessed_file = Path(payload["preprocessed_blend_file"])
        status = "Safe preprocess complete" if not payload["errors"] else "Safe preprocess found issues"
        self._finish_busy(status)
        self.logAdded.emit(
            "Preprocess: "
            f"{payload['original_triangle_count']:,} -> "
            f"{payload['preprocessed_triangle_count']:,} tris "
            f"({payload['reduction_percentage']:.2f}% removed)"
        )
        if payload.get("joined_mesh_objects"):
            self.logAdded.emit(
                "Preprocess model join: "
                f"{int(payload.get('original_object_count', 0)):,} mesh objects -> "
                f"{int(payload.get('preprocessed_object_count', 0)):,} model"
            )

    def _simplification_report_finished(self, report: object) -> None:
        payload = simplification_report_to_dict(report)
        image_path = Path(payload["heatmap_image_path"])
        payload["heatmap_image_url"] = _file_url(image_path)
        self._state["simplificationReport"] = payload
        status = (
            "Simplification analysis complete"
            if not payload["errors"]
            else "Simplification analysis found issues"
        )
        self._finish_busy(status)
        self.logAdded.emit(
            "Simplification: "
            f"{payload['removed_triangle_count']:,} triangles removed "
            f"({payload['reduction_percentage']:.2f}%)"
        )

    def _qem_heatmap_finished(self, report: object) -> None:
        payload = dict(report) if isinstance(report, dict) else {}
        image_path = Path(str(payload.get("heatmap_png", "")))
        inverse_image_path = Path(str(payload.get("heatmap_inverse_png", "")))
        feature_image_path = Path(str(payload.get("feature_heatmap_png", "")))
        feature_inverse_image_path = Path(str(payload.get("feature_heatmap_inverse_png", "")))
        ply_path = Path(str(payload.get("heatmap_ply", "")))
        feature_ply_path = Path(str(payload.get("feature_heatmap_ply", "")))
        payload["heatmap_png_url"] = _file_url(image_path)
        payload["heatmap_inverse_png_url"] = _file_url(inverse_image_path)
        payload["feature_heatmap_png_url"] = _file_url(feature_image_path)
        payload["feature_heatmap_inverse_png_url"] = _file_url(feature_inverse_image_path)
        payload["heatmap_ply_exists"] = ply_path.exists()
        payload["feature_heatmap_ply_exists"] = feature_ply_path.exists()
        self._state["qemHeatmap"] = payload
        status = "QEM cost heatmap complete" if not payload.get("errors") else "QEM heatmap found issues"
        self._finish_busy(status)
        stats = payload.get("cost_statistics", {})
        self.logAdded.emit(
            "QEM heatmap: "
            f"{int(payload.get('edge_count', 0)):,} edges, "
            f"median cost {float(stats.get('median', 0.0)):.6g}"
        )

    def _scale_analysis_finished(self, report: object) -> None:
        payload = dict(report) if isinstance(report, dict) else {}
        mean_path = Path(str(payload.get("mean_curvature_heatmap", "")))
        mean_inverse_path = Path(str(payload.get("mean_curvature_heatmap_inverse", "")))
        center_path = Path(str(payload.get("center_surround_heatmap", "")))
        center_inverse_path = Path(str(payload.get("center_surround_heatmap_inverse", "")))
        persistence_path = Path(str(payload.get("scale_persistence_heatmap", "")))
        persistence_inverse_path = Path(str(payload.get("scale_persistence_heatmap_inverse", "")))
        tiny_path = Path(str(payload.get("tiny_detail_heatmap", "")))
        tiny_inverse_path = Path(str(payload.get("tiny_detail_heatmap_inverse", "")))
        payload["mean_curvature_heatmap_url"] = _file_url(mean_path)
        payload["mean_curvature_heatmap_inverse_url"] = _file_url(mean_inverse_path)
        payload["center_surround_heatmap_url"] = _file_url(center_path)
        payload["center_surround_heatmap_inverse_url"] = _file_url(center_inverse_path)
        payload["scale_persistence_heatmap_url"] = _file_url(persistence_path)
        payload["scale_persistence_heatmap_inverse_url"] = _file_url(persistence_inverse_path)
        payload["tiny_detail_heatmap_url"] = _file_url(tiny_path)
        payload["tiny_detail_heatmap_inverse_url"] = _file_url(tiny_inverse_path)
        self._state["scaleAnalysis"] = payload
        status = (
            "Scale Analysis complete"
            if not payload.get("errors")
            else "Scale Analysis found issues"
        )
        self._finish_busy(status)
        interpretation = payload.get("interpretation", {})
        tiny_ratio = float(interpretation.get("tiny_detail_ratio", 0.0))
        self.logAdded.emit(
            "Scale Analysis: "
            f"{int(payload.get('vertex_count', 0)):,} vertices, "
            f"tiny detail ratio {tiny_ratio:.1%}"
        )

    def _afcost_candidates_finished(self, report: object) -> None:
        payload = dict(report) if isinstance(report, dict) else {}
        for candidate in payload.get("candidates", []) or []:
            image_path = Path(str(candidate.get("heatmap_png", "")))
            candidate["heatmap_png_url"] = _file_url(image_path)
        self._state["afcostCandidates"] = payload
        status = (
            "AF cost candidates complete"
            if not payload.get("errors")
            else "AF cost candidates found issues"
        )
        self._finish_busy(status)
        self.logAdded.emit(
            "AF cost candidates: "
            f"{int(payload.get('candidate_count', 0)):,} formulas, "
            f"{int(payload.get('edge_count', 0)):,} edges"
        )

    def _build_finished(self, report: object) -> None:
        payload = build_report_to_dict(report)
        if (
            self._current_preview_blend_file is not None
            and Path(payload["source_blend_file"]) == self._current_preview_blend_file
        ):
            payload["optimized"] = True
        self._state["build"] = payload
        self._finish_busy("Build complete" if not payload["errors"] else "Build issues found")
        self.logAdded.emit(f"Build folder: {payload['build_folder']}")
        self.logAdded.emit(
            "Optimization: enabled" if payload["optimized"] else "Optimization: disabled"
        )
        if payload.get("deploy_folder"):
            self.logAdded.emit(f"Cities Skylines import files: {payload['deploy_folder']}")

    def _pipeline_blend_file(self) -> Path:
        if self._preprocessed_file is not None and self._preprocessed_file.exists():
            return self._preprocessed_file
        if self._selected_file is None:
            raise FileNotFoundError("No selected blend file.")
        return self._selected_file

    def _saved_target_triangles(self) -> int:
        value = self._settings.value("targetTriangles", 3000)
        try:
            target_triangles = int(value)
        except (TypeError, ValueError):
            return 3000
        return max(100, target_triangles)

    def _progress(self, message: str) -> None:
        self._state["status"] = message
        self._emit_state()
        self.logAdded.emit(message)

    def _start_busy(self, status: str) -> bool:
        if self._busy:
            self.logAdded.emit("Another AssetForge task is already running.")
            self._debug_log(f"backend: busy gate rejected new task: {status}")
            return True
        self._busy = True
        self._state["busy"] = True
        self._state["status"] = status
        self._emit_state()
        self.logAdded.emit(status)
        self._debug_log(f"backend: busy started: {status}")
        return False

    def _finish_busy(self, status: str) -> None:
        self._busy = False
        self._state["busy"] = False
        self._state["status"] = status
        self._emit_state()
        self._debug_log(f"backend: busy finished: {status}")

    def _fail(self, message: str) -> None:
        self._busy = False
        self._state["busy"] = False
        self._state["status"] = "Operation failed"
        self._state["error"] = message
        self._emit_state()
        self.logAdded.emit(f"ERROR: {message}")
        self._debug_log(f"backend: operation failed: {message}")

    def _emit_state(self) -> None:
        payload = _json(self._state)
        self._debug_log(f"backend: stateChanged emit ({len(payload):,} chars)")
        self.stateChanged.emit(payload)

    def _run_on_ui(self, callback: Callable[[], object]) -> None:
        self.uiDispatch.emit(callback)

    @Slot(object)
    def _execute_ui_callback(self, callback: object) -> None:
        if callable(callback):
            try:
                callback()
            except Exception as exc:  # noqa: BLE001 - keep GUI recoverable from callback bugs.
                self._fail(f"GUI callback failed: {exc}")

    def _debug_log(self, message: str) -> None:
        base_dir = self._selected_file.parent if self._selected_file else Path.cwd()
        log_path = base_dir / "logs" / "assetforge_debug.log"
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        line = f"[{timestamp}] {message}"
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except OSError:
            pass
        self.logAdded.emit(f"DEBUG {message}")

    def _last_directory(self, key: str) -> str:
        value = self._settings.value(key)
        if value:
            path = Path(str(value))
            if path.exists():
                return str(path)
        return str(Path.home())

    def _current_output_folder(self) -> Path | None:
        value = self._state.get("outputFolder")
        return Path(str(value)) if value else None

    def _default_output_folder(self) -> tuple[Path | None, str]:
        saved = self._settings.value("lastOutputFolder")
        if saved:
            saved_path = Path(str(saved))
            if saved_path.exists():
                return saved_path, "manual"

        local_app_data = os.getenv("LOCALAPPDATA")
        if local_app_data:
            import_folder = (
                Path(local_app_data)
                / "Colossal Order"
                / "Cities_Skylines"
                / "Addons"
                / "Import"
            )
            if import_folder.exists():
                return import_folder, "auto"
            return import_folder, "auto-missing"

        return None, "not-found"


class WebMainWindow(QMainWindow):
    def __init__(
        self,
        analysis_service: VehicleAnalysisService,
        validation_service: VehicleValidationService,
        build_service: CitiesSkylinesBuildService,
        preprocess_service: PreprocessService,
        real_preview_service: RealOptimizationPreviewService,
        local_simplification_service: LocalSimplificationService,
        model_preview_service: ModelPreviewService,
        geometry_report_service: GeometryReportService,
        simplification_report_service: SimplificationReportService,
        qem_heatmap_service: QemHeatmapService,
        scale_analysis_service: ScaleAnalysisService,
        afcost_candidate_service: AFCostCandidateService,
        blender_configuration: BlenderConfigurationService,
    ) -> None:
        super().__init__()
        self.setWindowTitle("AssetForge")
        self._view = QWebEngineView()
        self._view.settings().setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls,
            True,
        )
        self._channel = QWebChannel(self._view.page())
        self._bridge = AssetForgeBridge(
            analysis_service,
            validation_service,
            build_service,
            preprocess_service,
            real_preview_service,
            local_simplification_service,
            model_preview_service,
            geometry_report_service,
            simplification_report_service,
            qem_heatmap_service,
            scale_analysis_service,
            afcost_candidate_service,
            blender_configuration,
        )
        self._channel.registerObject("assetForge", self._bridge)
        self._view.page().setWebChannel(self._channel)
        self.setCentralWidget(self._view)

        index = Path(__file__).parent / "web" / "index.html"
        self._view.setUrl(QUrl.fromLocalFile(str(index)))
        QTimer.singleShot(800, self._maybe_start_autotest)

    @Slot()
    def _maybe_start_autotest(self) -> None:
        blend_file = os.getenv("ASSETFORGE_AUTOTEST_BLEND")
        if not blend_file:
            return
        self._bridge._debug_log(f"backend: autotest loading blend {blend_file}")
        QTimer.singleShot(200, lambda: self._bridge.openBlendFile(blend_file))
