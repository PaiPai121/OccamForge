import pytest

from assetforge.domain.asset_profile import AssetProfileRegistry


def test_registry_contains_required_profiles() -> None:
    registry = AssetProfileRegistry()

    profile_ids = {profile.profile_id for profile in registry.all()}

    assert "generic_vehicle" in profile_ids
    assert "cities_skylines_vehicle" in profile_ids
    assert "cities_skylines_vehicle_strict" in profile_ids


def test_registry_rejects_unknown_profile() -> None:
    registry = AssetProfileRegistry()

    with pytest.raises(ValueError):
        registry.get("unknown")
