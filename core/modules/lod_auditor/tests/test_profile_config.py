# core/modules/lod_auditor/tests/test_profile_config.py
#
# Regression coverage for the profile-name allow-list fix (security audit,
# 2026-08-25): `load_profile(name)` used to silently fall back to the
# default profile for any unrecognised `name`, which let a client probe
# for arbitrary `.yaml` files elsewhere on disk (`name` reaches here
# straight from the client-controlled `LodAuditRequest.profile` field via
# api/routes/lod_audit.py) and use the default-vs-not behaviour as a
# file-existence oracle. Now rejected outright with UnknownProfileError.

import pytest

from lod_auditor.config import UnknownProfileError, available_profiles, load_profile


def test_shipped_profiles_load():
    for name in available_profiles():
        assert load_profile(name)


def test_unknown_profile_is_rejected():
    with pytest.raises(UnknownProfileError):
        load_profile("does_not_exist")


def test_path_traversal_profile_name_is_rejected():
    with pytest.raises(UnknownProfileError):
        load_profile("../../../../etc/passwd")


def test_available_profiles_is_the_allow_list():
    # "default" and "mobile" are the only two profiles every rule module
    # and the API layer are allowed to request.
    assert set(available_profiles()) == {"default", "mobile"}
