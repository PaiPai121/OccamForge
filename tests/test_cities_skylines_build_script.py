from pathlib import Path
import sys
import types

sys.modules.setdefault("bpy", types.SimpleNamespace())
from assetforge.blender.scripts.build_cities_skylines_asset import _copy_deploy_pair


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
