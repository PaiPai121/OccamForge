from pathlib import Path
import sys
import types

sys.modules.setdefault("bpy", types.SimpleNamespace())
from assetforge.blender.scripts.build_cities_skylines_asset import (
    _asset_stem,
    _copy_deploy_pair,
    _ensure_bake_uvs,
)


def test_copy_deploy_pair_uses_matching_asset_base(tmp_path: Path) -> None:
    source_fbx = tmp_path / "source.fbx"
    source_png = tmp_path / "source_d.png"
    deploy_folder = tmp_path / "import"
    deploy_folder.mkdir()
    source_fbx.write_bytes(b"fbx")
    source_png.write_bytes(b"png")
    (deploy_folder / "tank_cs.fbx").write_bytes(b"old fbx")
    (deploy_folder / "tank_cs_d.png").write_bytes(b"old png")
    (deploy_folder / "tank_cs_001.fbx").write_bytes(b"partial collision")

    deployed_fbx, deployed_png = _copy_deploy_pair(
        source_fbx,
        source_png,
        deploy_folder,
        "tank_cs",
    )

    assert deployed_fbx.name == "tank_cs_002.fbx"
    assert deployed_png.name == "tank_cs_002_d.png"
    assert deployed_fbx.read_bytes() == b"fbx"
    assert deployed_png.read_bytes() == b"png"


def test_asset_stem_strips_pipeline_suffixes() -> None:
    assert _asset_stem(Path("rhino_tank_preprocessed.blend")) == "rhino_tank"
    assert _asset_stem(Path("rhino_tank_optimized.blend")) == "rhino_tank"
    assert _asset_stem(Path("rhino_tank.blend")) == "rhino_tank"


class FakeUVLayers:
    def __init__(self) -> None:
        self.layers = []
        self.active_index = -1
        self.active_render = None

    def __iter__(self):
        return iter(self.layers)

    def __len__(self) -> int:
        return len(self.layers)

    def new(self, name: str):
        layer = types.SimpleNamespace(name=name)
        self.layers.append(layer)
        return layer


def test_ensure_bake_uvs_supports_active_render_without_render_index() -> None:
    uv_layers = FakeUVLayers()
    mesh = types.SimpleNamespace(uv_layers=uv_layers)
    obj = types.SimpleNamespace(data=mesh)

    _ensure_bake_uvs([obj])

    assert uv_layers.active_index == 0
    assert uv_layers.active_render is uv_layers.layers[0]
