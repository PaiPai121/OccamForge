from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThreadPool, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QSizePolicy,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from assetforge.domain.analysis import VehicleAnalysisReport
from assetforge.domain.optimization import VehicleOptimizationReport
from assetforge.gui.workers import AnalysisWorker, OptimizationWorker
from assetforge.services.blender_configuration import BlenderConfigurationService
from assetforge.services.vehicle_analysis import VehicleAnalysisService
from assetforge.services.vehicle_optimization import VehicleOptimizationService


class MainWindow(QMainWindow):
    def __init__(
        self,
        service: VehicleAnalysisService,
        optimization_service: VehicleOptimizationService,
        blender_configuration: BlenderConfigurationService,
    ) -> None:
        super().__init__()
        self._service = service
        self._optimization_service = optimization_service
        self._blender_configuration = blender_configuration
        self._selected_file: Path | None = None
        self._thread_pool = QThreadPool.globalInstance()

        self.setWindowTitle("AssetForge")
        self._build_ui()
        self._apply_styles()
        self._set_idle_state()

    def _build_ui(self) -> None:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(18)

        title = QLabel("AssetForge")
        title.setObjectName("title")
        subtitle = QLabel("Blender vehicle asset analysis")
        subtitle.setObjectName("subtitle")

        header = QVBoxLayout()
        header.setSpacing(4)
        header.addWidget(title)
        header.addWidget(subtitle)
        layout.addLayout(header)

        controls = QHBoxLayout()
        self.select_button = QPushButton("Select Blend File")
        self.select_button.clicked.connect(self._select_file)
        self.browse_blender_button = QPushButton("Browse Blender")
        self.browse_blender_button.clicked.connect(self._browse_blender)
        self.analyze_button = QPushButton("Analyze")
        self.analyze_button.clicked.connect(self._analyze)
        controls.addWidget(self.select_button)
        controls.addWidget(self.browse_blender_button)
        controls.addStretch(1)
        controls.addWidget(self.analyze_button)
        layout.addLayout(controls)

        optimize_controls = QHBoxLayout()
        self.profile_combo = QComboBox()
        for profile in self._optimization_service.profiles():
            self.profile_combo.addItem(profile.display_name, profile.profile_id)
        self.target_triangles_input = QSpinBox()
        self.target_triangles_input.setRange(100, 5_000_000)
        self.target_triangles_input.setSingleStep(500)
        self.target_triangles_input.setValue(5000)
        self.optimize_button = QPushButton("Optimize")
        self.optimize_button.clicked.connect(self._optimize)
        optimize_controls.addWidget(self._field_label("Profile:"))
        optimize_controls.addWidget(self.profile_combo)
        optimize_controls.addWidget(self._field_label("Target Triangles:"))
        optimize_controls.addWidget(self.target_triangles_input)
        optimize_controls.addWidget(self.optimize_button)
        layout.addLayout(optimize_controls)

        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("status")
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        layout.addWidget(self.status_label)
        layout.addWidget(self.progress)

        summary = QFrame()
        summary.setObjectName("summary")
        grid = QGridLayout(summary)
        grid.setContentsMargins(18, 16, 18, 16)
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(12)

        self.file_value = self._value_label("No file selected")
        self.body_value = self._value_label("Not analyzed")
        self.wheel_value = self._value_label("-")
        self.object_value = self._value_label("-")
        self.vertex_value = self._value_label("-")
        self.triangle_value = self._value_label("-")
        self.original_triangles_value = self._value_label("-")
        self.optimized_triangles_value = self._value_label("-")
        self.reduction_value = self._value_label("-")

        rows = [
            ("Selected File:", self.file_value),
            ("VehicleBody:", self.body_value),
            ("Wheel Count:", self.wheel_value),
            ("Objects:", self.object_value),
            ("Vertices:", self.vertex_value),
            ("Triangles:", self.triangle_value),
            ("Original Triangles:", self.original_triangles_value),
            ("Optimized Triangles:", self.optimized_triangles_value),
            ("Reduction:", self.reduction_value),
        ]
        for row, (label, value) in enumerate(rows):
            grid.addWidget(self._field_label(label), row, 0)
            grid.addWidget(value, row, 1)
        grid.setColumnStretch(1, 1)
        layout.addWidget(summary)

        log_label = QLabel("Output Log")
        log_label.setObjectName("sectionLabel")
        self.output_log = QTextEdit()
        self.output_log.setReadOnly(True)
        self.output_log.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(log_label)
        layout.addWidget(self.output_log, 1)

        self.setCentralWidget(root)

    def _field_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("fieldLabel")
        label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return label

    def _value_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("fieldValue")
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        return label

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget { background: #f6f7f9; color: #20242a; font-size: 14px; }
            QLabel#title { font-size: 28px; font-weight: 700; }
            QLabel#subtitle { color: #667085; }
            QLabel#status { color: #344054; }
            QLabel#sectionLabel { font-weight: 700; }
            QLabel#fieldLabel { color: #667085; font-weight: 600; }
            QLabel#fieldValue { color: #101828; }
            QFrame#summary { background: #ffffff; border: 1px solid #d0d5dd; border-radius: 8px; }
            QPushButton {
                background: #1f6feb; color: white; border: 0; border-radius: 6px;
                padding: 9px 14px; font-weight: 600;
            }
            QPushButton:disabled { background: #98a2b3; }
            QTextEdit {
                background: #101828; color: #d0d5dd; border: 1px solid #344054;
                border-radius: 8px; padding: 10px; font-family: Consolas, monospace;
            }
            QProgressBar { border: 1px solid #d0d5dd; border-radius: 4px; height: 8px; }
            QProgressBar::chunk { background: #12b76a; border-radius: 4px; }
            """
        )

    def _set_idle_state(self) -> None:
        self.analyze_button.setEnabled(self._selected_file is not None)
        self.optimize_button.setEnabled(self._selected_file is not None)
        self.progress.setRange(0, 1)
        self.progress.setValue(0)

    def _select_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Blender File",
            str(Path.home()),
            "Blender Files (*.blend)",
        )
        if not path:
            return
        self._selected_file = Path(path)
        self.file_value.setText(self._selected_file.name)
        self.body_value.setText("Not analyzed")
        self.wheel_value.setText("-")
        self.object_value.setText("-")
        self.vertex_value.setText("-")
        self.triangle_value.setText("-")
        self.original_triangles_value.setText("-")
        self.optimized_triangles_value.setText("-")
        self.reduction_value.setText("-")
        self.status_label.setText("Ready to analyze")
        self.output_log.append(f"Selected file: {self._selected_file}")
        self._set_idle_state()

    def _browse_blender(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select blender.exe",
            str(Path.home()),
            "Blender Executable (blender.exe)",
        )
        if not path:
            return
        try:
            result = self._blender_configuration.save_manual_path(Path(path))
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid Blender Executable", str(exc))
            return
        self.output_log.append(f"Blender configured from {result.source}: {result.executable}")
        self.status_label.setText("Blender configured")

    def _analyze(self) -> None:
        if self._selected_file is None:
            QMessageBox.warning(self, "No file selected", "Select a .blend file before analyzing.")
            return

        self._set_busy_state()
        worker = AnalysisWorker(self._service, self._selected_file)
        worker.signals.started.connect(lambda: self.output_log.append("Analysis started."))
        worker.signals.finished.connect(self._analysis_finished)
        worker.signals.failed.connect(self._analysis_failed)
        self._thread_pool.start(worker)

    def _optimize(self) -> None:
        if self._selected_file is None:
            QMessageBox.warning(self, "No file selected", "Select a .blend file before optimizing.")
            return

        self._set_busy_state("Preparing optimization...")
        worker = OptimizationWorker(
            self._service,
            self._optimization_service,
            self._selected_file,
            str(self.profile_combo.currentData()),
            self.target_triangles_input.value(),
        )
        worker.signals.started.connect(lambda: self.output_log.append("Optimization started."))
        worker.signals.progress.connect(self._optimization_progress)
        worker.signals.analysis_finished.connect(self._optimization_analysis_finished)
        worker.signals.finished.connect(self._optimization_finished)
        worker.signals.failed.connect(self._analysis_failed)
        self._thread_pool.start(worker)

    def _set_busy_state(self, status: str = "Analyzing with Blender...") -> None:
        self.select_button.setEnabled(False)
        self.browse_blender_button.setEnabled(False)
        self.analyze_button.setEnabled(False)
        self.optimize_button.setEnabled(False)
        self.profile_combo.setEnabled(False)
        self.target_triangles_input.setEnabled(False)
        self.status_label.setText(status)
        self.progress.setRange(0, 0)

    def _restore_controls(self) -> None:
        self.select_button.setEnabled(True)
        self.browse_blender_button.setEnabled(True)
        self.profile_combo.setEnabled(True)
        self.target_triangles_input.setEnabled(True)
        self._set_idle_state()

    def _analysis_finished(self, report: VehicleAnalysisReport) -> None:
        self._restore_controls()
        self._display_analysis_report(report)

    def _optimization_analysis_finished(self, report: VehicleAnalysisReport) -> None:
        self._display_analysis_report(report)

    def _display_analysis_report(self, report: VehicleAnalysisReport) -> None:
        self.body_value.setText("Found" if report.has_vehicle_body else "Missing")
        self.wheel_value.setText(str(report.wheel_count))
        self.object_value.setText(str(report.object_count))
        self.vertex_value.setText(f"{report.vertex_count:,}")
        self.triangle_value.setText(f"{report.triangle_count:,}")
        self.status_label.setText("Analysis complete" if report.is_successful else "Issues found")
        self._append_report(report)
        if report.errors:
            QMessageBox.warning(self, "Analysis Issues", "\n".join(report.errors))

    def _analysis_failed(self, message: str) -> None:
        self._restore_controls()
        self.status_label.setText("Analysis failed")
        self.output_log.append(f"ERROR: {message}")
        if "Blender executable was not found" in message:
            response = QMessageBox.question(
                self,
                "Blender Not Found",
                f"{message}\n\nBrowse for blender.exe now?",
            )
            if response == QMessageBox.StandardButton.Yes:
                self._browse_blender()
            return
        QMessageBox.critical(self, "Analysis Failed", message)

    def _optimization_progress(self, message: str) -> None:
        self.status_label.setText(message)
        self.output_log.append(message)

    def _optimization_finished(self, report: VehicleOptimizationReport) -> None:
        self._restore_controls()
        self.status_label.setText("Optimization complete" if report.is_successful else "Issues found")
        self.original_triangles_value.setText(f"{report.original_triangle_count:,}")
        self.optimized_triangles_value.setText(f"{report.optimized_triangle_count:,}")
        self.reduction_value.setText(f"{report.reduction_percentage:.2f}%")
        self._append_optimization_report(report)
        if report.errors:
            QMessageBox.warning(self, "Optimization Issues", "\n".join(report.errors))

    def _append_report(self, report: VehicleAnalysisReport) -> None:
        self.output_log.append("")
        self.output_log.append(f"File: {report.blend_file}")
        self.output_log.append(f"VehicleBody: {'Found' if report.has_vehicle_body else 'Missing'}")
        self.output_log.append(f"Wheels: {report.wheel_count}")
        self.output_log.append(f"Objects: {report.object_count}")
        self.output_log.append(f"Vertices: {report.vertex_count}")
        self.output_log.append(f"Triangles: {report.triangle_count}")
        for warning in report.warnings:
            self.output_log.append(f"WARNING: {warning}")
        for error in report.errors:
            self.output_log.append(f"ERROR: {error}")

    def _append_optimization_report(self, report: VehicleOptimizationReport) -> None:
        self.output_log.append("")
        self.output_log.append(f"Optimized File: {report.optimized_blend_file}")
        self.output_log.append(f"Optimization Report: {report.report_file}")
        self.output_log.append(f"Profile: {report.profile_id}")
        self.output_log.append(f"Target Triangles: {report.target_triangle_count}")
        self.output_log.append(f"Original Triangles: {report.original_triangle_count}")
        self.output_log.append(f"Optimized Triangles: {report.optimized_triangle_count}")
        self.output_log.append(f"Reduction: {report.reduction_percentage:.2f}%")
        self.output_log.append(f"Decimate Ratio: {report.decimate_ratio:.4f}")
        for warning in report.warnings:
            self.output_log.append(f"WARNING: {warning}")
        for error in report.errors:
            self.output_log.append(f"ERROR: {error}")
