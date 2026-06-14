from __future__ import annotations

import json
from pathlib import Path

from assetforge.domain.analysis import VehicleAnalysisReport
from assetforge.gui.web_main_window import AssetForgeBridge


class FakeAnalysisService:
    def __init__(self, preview_mesh_path: Path) -> None:
        self._preview_mesh_path = preview_mesh_path

    def analyze_vehicle(self, blend_file: Path) -> VehicleAnalysisReport:
        return VehicleAnalysisReport(
            blend_file=blend_file,
            has_vehicle_body=True,
            wheel_count=4,
            object_count=5,
            vertex_count=100,
            triangle_count=200,
            preview_mesh_path=self._preview_mesh_path,
        )


class UnusedService:
    pass


def test_analysis_worker_updates_web_state_on_ui_thread(qtbot, tmp_path: Path) -> None:
    blend_file = tmp_path / "vehicle.blend"
    blend_file.write_bytes(b"fake blend")
    preview_mesh = tmp_path / "previews" / "vehicle_viewport.obj"
    preview_mesh.parent.mkdir()
    preview_mesh.write_text("v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n", encoding="utf-8")

    bridge = AssetForgeBridge(
        FakeAnalysisService(preview_mesh),
        UnusedService(),
        UnusedService(),
        UnusedService(),
        UnusedService(),
        UnusedService(),
    )
    bridge._selected_file = blend_file

    received: list[dict[str, object]] = []
    bridge.stateChanged.connect(lambda payload: received.append(json.loads(payload)))

    bridge._begin_analysis("Loading original model preview...", "Analysis started.")

    qtbot.waitUntil(
        lambda: any(item.get("analysis") for item in received),
        timeout=3000,
    )

    final_state = next(item for item in reversed(received) if item.get("analysis"))
    analysis = final_state["analysis"]
    assert analysis["triangle_count"] == 200
    assert analysis["preview_mesh_path"] == str(preview_mesh)
    assert analysis["preview_mesh_url"].startswith("file:///")
    assert final_state["busy"] is False


def test_load_preview_mesh_returns_mesh_text(tmp_path: Path) -> None:
    preview_mesh = tmp_path / "vehicle_viewport.obj"
    mesh_text = "v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n"
    preview_mesh.write_text(mesh_text, encoding="utf-8")
    bridge = AssetForgeBridge(
        FakeAnalysisService(preview_mesh),
        UnusedService(),
        UnusedService(),
        UnusedService(),
        UnusedService(),
        UnusedService(),
    )

    assert bridge.loadPreviewMesh(str(preview_mesh)) == mesh_text
