from __future__ import annotations

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
from assetforge.models.model_preview_dto import model_preview_report_to_dict
from assetforge.models.real_optimization_preview_dto import real_preview_report_to_dict
from assetforge.models.validation_dto import validation_report_to_dict
from assetforge.gui.workers import (
    AnalysisWorker,
    CitiesSkylinesBuildWorker,
    ModelPreviewWorker,
    RealOptimizationPreviewWorker,
    ValidationWorker,
)
from assetforge.services.blender_configuration import BlenderConfigurationService
from assetforge.services.cities_skylines_build import CitiesSkylinesBuildService
from assetforge.services.model_preview import ModelPreviewService
from assetforge.services.real_optimization_preview import RealOptimizationPreviewService
from assetforge.services.vehicle_analysis import VehicleAnalysisService
from assetforge.services.vehicle_validation import VehicleValidationService


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload)


class AssetForgeBridge(QObject):
    stateChanged = Signal(str)
    logAdded = Signal(str)
    uiDispatch = Signal(object)

    def __init__(
        self,
        analysis_service: VehicleAnalysisService,
        validation_service: VehicleValidationService,
        build_service: CitiesSkylinesBuildService,
        real_preview_service: RealOptimizationPreviewService,
        model_preview_service: ModelPreviewService,
        blender_configuration: BlenderConfigurationService,
    ) -> None:
        super().__init__()
        self._analysis_service = analysis_service
        self._validation_service = validation_service
        self._build_service = build_service
        self._real_preview_service = real_preview_service
        self._model_preview_service = model_preview_service
        self._blender_configuration = blender_configuration
        self._thread_pool = QThreadPool.globalInstance()
        self._active_workers: list[object] = []
        self._selected_file: Path | None = None
        self._current_preview_target: int | None = None
        self._busy = False
        self._analysis_generation = 0
        self._source_preview_generation = 0
        self._settings = QSettings("AssetForge", "AssetForge")
        output_folder, output_source = self._default_output_folder()
        self.uiDispatch.connect(
            self._execute_ui_callback,
            Qt.ConnectionType.QueuedConnection,
        )
        self._state: dict[str, Any] = {
            "selectedFile": None,
            "targetTriangles": 15000,
            "optimizeEnabled": False,
            "busy": False,
            "sourcePreviewBusy": False,
            "status": "Choose a Blender vehicle file",
            "analysis": None,
            "validation": None,
            "sourcePreview": None,
            "realPreview": None,
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
            self._debug_log("backend: autotest first frame observed; exiting")
            QTimer.singleShot(0, QApplication.instance().quit)

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

    @Slot(result=str)
    def selectBlendFile(self) -> str:
        path, _ = QFileDialog.getOpenFileName(
            None,
            "Select Blender File",
            self._last_directory("lastBlendDirectory"),
            "Blender Files (*.blend)",
        )
        if path:
            self.openBlendFile(path)
        return _json(self._state)

    @Slot(str, result=str)
    def openBlendFile(self, path: str) -> str:
        blend_file = Path(path)
        if not blend_file.exists() or blend_file.suffix.lower() != ".blend":
            self._fail(f"Expected an existing .blend file, got: {blend_file}")
            return _json(self._state)
        self._selected_file = blend_file
        self._settings.setValue("lastBlendDirectory", str(self._selected_file.parent))
        self._state.update(
            {
                "selectedFile": str(self._selected_file),
                "analysis": None,
                "validation": None,
                "sourcePreview": None,
                "sourcePreviewBusy": False,
                "realPreview": None,
                "build": None,
                "currentPreviewTarget": None,
                "status": "Loading original model preview...",
            }
        )
        self._current_preview_target = None
        self._emit_state()
        self.logAdded.emit(f"Selected file: {self._selected_file}")
        self._debug_log(f"backend: selected file {self._selected_file}")
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
        self._analysis_generation += 1
        self._begin_analysis("Analyzing vehicle structure...", "Analysis started.")

    def _auto_analyze_selected_file(self, generation: int) -> None:
        if generation != self._analysis_generation:
            return
        self._begin_analysis(
            "Loading original model preview...",
            "Opening Blender in the background to read the original model.",
        )

    def _begin_analysis(self, status: str, started_log: str) -> None:
        if not self._selected_file:
            return
        if self._start_busy(status):
            return
        self._debug_log(f"backend: analysis worker queued for {self._selected_file}")
        worker = AnalysisWorker(self._analysis_service, self._selected_file)
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

    @Slot(int)
    def generateRealPreview(self, target_triangles: int) -> None:
        if not self._selected_file:
            self.logAdded.emit("Select a .blend file before generating a preview.")
            return
        if target_triangles <= 0:
            self.logAdded.emit("Target triangles must be greater than zero.")
            return
        if self._start_busy("Generating real optimization preview..."):
            return
        self._state["targetTriangles"] = target_triangles
        self._state["realPreview"] = None
        self._state["currentPreviewTarget"] = None
        self._current_preview_target = None
        worker = RealOptimizationPreviewWorker(
            self._real_preview_service,
            self._selected_file,
            "cities_skylines_vehicle",
            target_triangles,
            self._selected_file.parent / "previews",
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

    @Slot()
    def applyCurrentPreview(self) -> None:
        if self._current_preview_target is None:
            return
        self._state["targetTriangles"] = self._current_preview_target
        self._state["optimizeEnabled"] = True
        self._state["status"] = f"Selected {self._current_preview_target:,} tris as build target"
        self._emit_state()

    @Slot(bool)
    def setOptimizeEnabled(self, enabled: bool) -> None:
        self._state["optimizeEnabled"] = enabled

    @Slot()
    def validate(self) -> None:
        if not self._selected_file or self._start_busy("Validating asset readiness..."):
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

    @Slot(int, bool)
    def buildCitiesSkylinesAsset(self, target_triangles: int, optimize: bool) -> None:
        if not self._selected_file:
            self.logAdded.emit("Select a .blend file before building.")
            return
        if target_triangles <= 0:
            self.logAdded.emit("Target triangles must be greater than zero.")
            return
        self._state["targetTriangles"] = target_triangles
        self._state["optimizeEnabled"] = optimize
        if self._start_busy("Building Cities Skylines package..."):
            return
        worker = CitiesSkylinesBuildWorker(
            self._build_service,
            self._selected_file,
            self._current_output_folder(),
            optimize,
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
        payload["preview_image_url"] = image_path.resolve().as_uri() if image_path.exists() else None
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
        for item in payload["items"]:
            image_path = Path(item["preview_image_path"])
            item["preview_image_url"] = image_path.resolve().as_uri() if image_path.exists() else None
        self._state["realPreview"] = payload
        if payload["items"] and not payload["items"][0]["errors"]:
            self._current_preview_target = int(payload["items"][0]["target_triangles"])
            self._state["currentPreviewTarget"] = self._current_preview_target
        self._finish_busy("Real preview complete" if not payload["errors"] else "Real preview issues found")
        if payload["items"]:
            item = payload["items"][0]
            self.logAdded.emit(
                f"Preview: target {item['target_triangles']:,}, actual "
                f"{item['actual_triangles']:,}, reduction {item['reduction_percent']:.2f}%"
            )

    def _validation_finished(self, report: object) -> None:
        payload = validation_report_to_dict(report)
        self._state["validation"] = payload
        self._finish_busy(f"Validation complete: {payload['rating']}")
        self.logAdded.emit(f"Validation score: {payload['score']} ({payload['rating']})")

    def _build_finished(self, report: object) -> None:
        payload = build_report_to_dict(report)
        self._state["build"] = payload
        self._finish_busy("Build complete" if not payload["errors"] else "Build issues found")
        self.logAdded.emit(f"Build folder: {payload['build_folder']}")
        self.logAdded.emit(
            "Optimization: enabled" if payload["optimized"] else "Optimization: disabled"
        )
        if payload.get("deploy_folder"):
            self.logAdded.emit(f"Cities Skylines import files: {payload['deploy_folder']}")

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
            callback()

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
        real_preview_service: RealOptimizationPreviewService,
        model_preview_service: ModelPreviewService,
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
            real_preview_service,
            model_preview_service,
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
