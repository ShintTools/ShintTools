# core/modules/predictive/tests/test_platform_profiles.py

from predictive.cost_model.platform_profiles import (
    DEFAULT_PROFILE,
    available_platform_profiles,
    load_platform_profile,
)

EXPECTED_PROFILES = {
    "desktop_60",
    "desktop_144",
    "console_30",
    "console_60",
    "mobile_30",
    "vr_90",
    "steamdeck_60",
}


def test_all_shipped_profiles_load():
    names = {p.profile for p in available_platform_profiles()}
    assert names == EXPECTED_PROFILES


def test_default_profile_is_calibrated_baseline():
    p = load_platform_profile(DEFAULT_PROFILE)
    assert p.profile == "desktop_60"
    assert p.is_calibrated  # ground truth is measured on this hardware
    assert p.hw_scale_factor == 1.0


def test_unknown_profile_falls_back_to_default():
    assert load_platform_profile("does_not_exist").profile == DEFAULT_PROFILE


def test_uncalibrated_profiles_declare_it():
    # Profiles scaled from the baseline must say so — the orchestrator caps
    # their confidence at "medium" based on this flag.
    for name in ("console_30", "mobile_30", "steamdeck_60"):
        assert not load_platform_profile(name).is_calibrated


def test_budgets_are_positive_and_coherent():
    for p in available_platform_profiles():
        assert p.frame_budget_ms > 0
        assert 0 < p.cpu_budget_ms <= p.frame_budget_ms * 2
        assert 0 < p.gpu_budget_ms <= p.frame_budget_ms * 2
        assert p.vram_budget_mb > 0 and p.ram_budget_mb > 0
        # frame budget must match the declared fps target (±1%)
        assert abs(p.frame_budget_ms - 1000.0 / p.target_fps) < 0.01 * (
            1000.0 / p.target_fps
        ) + 0.05


def test_vr_is_strict_and_deck_is_unified():
    assert load_platform_profile("vr_90").strict_budget
    assert load_platform_profile("steamdeck_60").unified_memory
