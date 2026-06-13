from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AssetProfile:
    """Optimization rules for a target asset type."""

    profile_id: str
    display_name: str
    default_target_triangles: int
    preserve_wheels: bool = True
    decimate_body_only: bool = False
    minimum_decimate_ratio: float = 0.05
    max_decimation_iterations: int = 12
    preferred_triangle_count: int = 5000
    warning_triangle_count: int = 10000
    critical_triangle_count: int = 20000


GENERIC_VEHICLE_PROFILE = AssetProfile(
    profile_id="generic_vehicle",
    display_name="Generic Vehicle",
    default_target_triangles=5000,
    decimate_body_only=False,
    preferred_triangle_count=5000,
    warning_triangle_count=10000,
    critical_triangle_count=20000,
)

CITIES_SKYLINES_VEHICLE_PROFILE = AssetProfile(
    profile_id="cities_skylines_vehicle",
    display_name="Cities Skylines Vehicle",
    default_target_triangles=5000,
    decimate_body_only=False,
    preferred_triangle_count=5000,
    warning_triangle_count=10000,
    critical_triangle_count=20000,
)

CITIES_SKYLINES_VEHICLE_STRICT_PROFILE = AssetProfile(
    profile_id="cities_skylines_vehicle_strict",
    display_name="Cities Skylines Vehicle Strict",
    default_target_triangles=5000,
    decimate_body_only=False,
    preferred_triangle_count=5000,
    warning_triangle_count=10000,
    critical_triangle_count=20000,
)


class AssetProfileRegistry:
    def __init__(self, profiles: tuple[AssetProfile, ...] | None = None) -> None:
        self._profiles = profiles or (
            GENERIC_VEHICLE_PROFILE,
            CITIES_SKYLINES_VEHICLE_PROFILE,
            CITIES_SKYLINES_VEHICLE_STRICT_PROFILE,
        )

    def get(self, profile_id: str) -> AssetProfile:
        for profile in self._profiles:
            if profile.profile_id == profile_id:
                return profile
        valid_ids = ", ".join(profile.profile_id for profile in self._profiles)
        raise ValueError(f"Unknown asset profile '{profile_id}'. Valid profiles: {valid_ids}")

    def all(self) -> tuple[AssetProfile, ...]:
        return self._profiles
