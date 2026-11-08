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
        catalog.plugin_version_url("0.13.367"): {"info": {"requires_dist": [plugin_required]}},
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
        catalog.latest_pair(
            _catalog(plugin_required="homeassistant>=2026.9.4"), "2026.9.0", "3.14.7"
        )


def test_python_requirement_change_needs_review():
    with pytest.raises(catalog.ReviewNeeded, match="Python"):
        catalog.latest_pair(_catalog(ha_python=">=3.15"), "2026.9.0", "3.14.7")


def test_missing_release_list_fails_closed():
    with pytest.raises(catalog.ReviewNeeded, match="release list"):
        catalog.latest_pair(lambda url: {}, "2026.9.0", "3.14.7")


def test_metadata_request_is_bounded_and_host_restricted(monkeypatch):
    with pytest.raises(ValueError, match="Unexpected"):
        catalog.fetch_pypi_json("https://example.com/pypi/homeassistant/json")

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self, size):
            assert size == catalog.MAX_RESPONSE_BYTES + 1
            return b'{"releases": {}}'

    monkeypatch.setattr(catalog, "urlopen", lambda request, timeout: Response())
    assert catalog.fetch_pypi_json(catalog.HA_URL) == {"releases": {}}


def test_new_ha_uses_official_plugin_instead_of_retired_package():
    seen = []

    def fetch(url):
        seen.append(url)
        if url == catalog.HA_URL:
            return {"releases": {"2026.11.0": [{"yanked": False}]}}
        if url == "https://pypi.org/pypi/pytest-homeassistant/json":
            return {"releases": {"2026.11.0": [{"yanked": False}]}}
        if url == "https://pypi.org/pypi/pytest-homeassistant/2026.11.0/json":
            return {"info": {"requires_dist": ["homeassistant==2026.11.0"]}}
        raise AssertionError(f"Unexpected endpoint: {url}")

    assert catalog.latest_pair(fetch, "2026.10.4", "3.14.7") == ("2026.11.0", "2026.11.0")
    assert catalog.PLUGIN_URL not in seen


def test_official_plugin_missing_stable_version_waits_without_using_beta():
    def fetch(url):
        if url == catalog.HA_URL:
            return {"releases": {"2026.11.1": [{"yanked": False}]}}
        if url == "https://pypi.org/pypi/pytest-homeassistant/json":
            return {"releases": {"0.1.3": [{"yanked": False}], "2026.11.1b1": [{"yanked": False}]}}
        raise AssertionError("No matching stable plugin metadata should be fetched")

    with pytest.raises(catalog.PluginUnavailable, match="pytest-homeassistant.*2026.11.1"):
        catalog.latest_pair(fetch, "2026.11.0", "3.14.7")


@pytest.mark.parametrize(
    ("python_requires", "ha_requires", "reason"),
    [
        (">=3.15", "homeassistant==2026.11.0", "different Python"),
        (">=3.14.2", "homeassistant>=2026.11.0", "does not pin"),
    ],
)
def test_published_official_plugin_incompatibility_is_not_waiting(
    python_requires, ha_requires, reason
):
    def fetch(url):
        if url == catalog.HA_URL:
            return {"releases": {"2026.11.0": [{"yanked": False}]}}
        if url == "https://pypi.org/pypi/pytest-homeassistant/json":
            return {
                "releases": {"2026.11.0": [{"yanked": False, "requires_python": python_requires}]}
            }
        return {"info": {"requires_dist": [ha_requires]}}

    with pytest.raises(catalog.ReviewNeeded, match=reason) as caught:
        catalog.latest_pair(fetch, "2026.10.4", "3.14.7")
    assert not isinstance(caught.value, catalog.PluginUnavailable)


@pytest.mark.parametrize("files", ["not-a-file-list", [None], [{"yanked": "false"}]])
def test_malformed_matching_official_release_remains_a_failure(files):
    def fetch(url):
        if url == catalog.HA_URL:
            return {"releases": {"2026.11.1": [{"yanked": False}]}}
        return {"releases": {"2026.11.1": files}}

    with pytest.raises(catalog.ReviewNeeded, match="Malformed") as caught:
        catalog.latest_pair(fetch, "2026.11.0", "3.14.7")
    assert not isinstance(caught.value, catalog.PluginUnavailable)


@pytest.mark.parametrize("files", [[], [{"yanked": True}]])
def test_empty_or_withdrawn_official_release_waits(files):
    def fetch(url):
        if url == catalog.HA_URL:
            return {"releases": {"2026.11.1": [{"yanked": False}]}}
        return {"releases": {"2026.11.1": files}}

    with pytest.raises(catalog.PluginUnavailable):
        catalog.latest_pair(fetch, "2026.11.0", "3.14.7")
