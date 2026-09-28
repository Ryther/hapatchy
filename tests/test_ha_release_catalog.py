"""The updater selects only a published, compatible HA/plugin pair."""

import pytest

from script import ha_release_catalog as catalog


def _catalog(*, plugin_required="homeassistant==2026.9.4", ha_python=">=3.14.2"):
    responses = {
        catalog.HA_URL: {
            "releases": {
                "2026.9.0": [{"yanked": False, "requires_python": ">=3.14.2"}],
                "2026.9.4": [{"yanked": False, "requires_python": ha_python}],
                "2026.10.0b1": [{"yanked": False, "requires_python": ">=3.14.2"}],
                "2026.10.0": [{"yanked": True, "requires_python": ">=3.14.2"}],
            }
        },
        catalog.PLUGIN_URL: {
            "releases": {
                "0.13.366": [{"yanked": False}],
                "0.13.367": [{"yanked": False}],
                "0.13.368": [{"yanked": True}],
            }
        },
        catalog.plugin_version_url("0.13.367"): {
            "info": {"requires_dist": [plugin_required]}
        },
        catalog.plugin_version_url("0.13.366"): {
            "info": {"requires_dist": ["homeassistant==2026.9.3"]}
        },
    }
    return responses.__getitem__


def test_latest_stable_exact_pair_ignores_beta_and_yanked():
    assert catalog.latest_pair(_catalog(), "2026.9.0", "3.14.7") == (
        "2026.9.4",
        "0.13.367",
    )


def test_noop_at_current_baseline():
    assert catalog.latest_pair(_catalog(), "2026.9.4", "3.14.7") is None


def test_missing_exact_plugin_needs_review():
    with pytest.raises(catalog.ReviewNeeded, match="exact pytest plugin"):
        catalog.latest_pair(_catalog(plugin_required="homeassistant>=2026.9.4"), "2026.9.0", "3.14.7")


def test_python_requirement_change_needs_review():
    with pytest.raises(catalog.ReviewNeeded, match="Python"):
        catalog.latest_pair(_catalog(ha_python=">=3.15"), "2026.9.0", "3.14.7")
