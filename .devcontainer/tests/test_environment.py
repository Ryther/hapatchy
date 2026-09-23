"""Behavioral checks for development-state preservation and invalidation."""

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

MODULE = Path(__file__).parents[1] / "scripts" / "environment.py"


class EnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(MODULE.is_file(), "Environment bootstrap is not implemented")
        spec = importlib.util.spec_from_file_location("environment", MODULE)
        self.env = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.env)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / ".devcontainer").mkdir()
        (self.root / ".devcontainer/configuration.yaml").write_text("frontend:\n")

    def test_existing_configuration_is_never_overwritten(self):
        self.env.prepare_config(self.root, mutate=True)
        config = self.root / ".devcontainer/state/ha/configuration.yaml"
        config.write_text("owner configuration\n")
        self.env.prepare_config(self.root, mutate=True)
        self.assertEqual(config.read_text(), "owner configuration\n")

    def test_no_product_code_required(self):
        self.env.prepare_config(self.root, mutate=True)
        self.assertFalse((self.root / ".devcontainer/state/ha/custom_components/hapatchy").exists())

    def test_source_link_created_then_validated(self):
        source = self.root / "custom_components/hapatchy"
        source.mkdir(parents=True)
        self.env.prepare_config(self.root, mutate=True)
        target = self.root / ".devcontainer/state/ha/custom_components/hapatchy"
        self.assertTrue(target.is_symlink())
        self.assertEqual(target.resolve(), source)
        self.env.prepare_config(self.root, mutate=False)

    def test_conflicting_source_link_is_preserved_and_rejected(self):
        (self.root / "custom_components/hapatchy").mkdir(parents=True)
        target = self.root / ".devcontainer/state/ha/custom_components/hapatchy"
        target.parent.mkdir(parents=True)
        target.write_text("preserve me")
        with self.assertRaises(RuntimeError):
            self.env.prepare_config(self.root, mutate=True)
        self.assertEqual(target.read_text(), "preserve me")

    def test_live_bootstrap_never_initializes_missing_state(self):
        with self.assertRaises(RuntimeError):
            self.env.prepare_config(self.root, mutate=False)
        self.assertFalse((self.root / ".devcontainer/state").exists())

    def test_private_directory_rejects_symlink(self):
        target = self.root / "private"
        target.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(RuntimeError):
            self.env.ensure_private_dir(target)
        self.assertTrue(target.is_symlink())

    def test_state_directory_symlink_is_rejected(self):
        (self.root / ".devcontainer/state").symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(RuntimeError):
            self.env.prepare_config(self.root, mutate=True)

    def test_reused_pid_does_not_count_as_live_service(self):
        marker = self.root / "service.pid"
        marker.write_text(json.dumps({"pid": os.getpid(), "start_time": "old-process"}))
        self.assertFalse(self.env.running(marker))

    def test_matching_live_process_identity_is_detected(self):
        marker = self.root / "service.pid"
        start = Path("/proc/self/stat").read_text().rsplit(")", 1)[1].split()[19]
        marker.write_text(json.dumps({"pid": os.getpid(), "start_time": start}))
        self.assertTrue(self.env.running(marker))

    def test_image_and_lock_changes_invalidate_environment(self):
        lock = self.root / "requirements.txt"
        lock.write_text("example==1.0\n")
        a = self.env.environment_marker(lock, {"base_image": "digest-a", "build_inputs": "a"})
        lock.write_text("example==2.0\n")
        b = self.env.environment_marker(lock, {"base_image": "digest-a", "build_inputs": "a"})
        c = self.env.environment_marker(lock, {"base_image": "digest-b", "build_inputs": "a"})
        d = self.env.environment_marker(lock, {"base_image": "digest-b", "build_inputs": "b"})
        self.assertNotEqual(a, b)
        self.assertNotEqual(b, c)
        self.assertNotEqual(c, d)

    def test_interpreter_platform_and_architecture_invalidate_environment(self):
        lock = self.root / "requirements.txt"
        lock.write_text("example==1.0\n")
        original = self.env.environment_marker(lock, {})
        for owner, name in [
            (self.env.platform, "python_version"),
            (self.env.platform, "machine"),
            (self.env.sysconfig, "get_platform"),
        ]:
            with (
                self.subTest(input=name),
                patch.object(owner, name, return_value="changed"),
            ):
                self.assertNotEqual(original, self.env.environment_marker(lock, {}))

    def test_failed_install_never_publishes_success_marker(self):
        lock = self.root / ".devcontainer/requirements-tools.txt"
        lock.write_text("unavailable==0\n")
        import subprocess

        with (
            patch.object(self.env, "run", side_effect=subprocess.CalledProcessError(1, "pip")),
            self.assertRaises(subprocess.CalledProcessError),
        ):
            self.env.prepare_venv(self.root, ".venv", lock.name, {}, live=False)
        self.assertFalse((self.root / ".venv/.hapatchy-environment.json").exists())

    def test_live_changed_or_missing_marker_preserves_environment(self):
        lock = self.root / ".devcontainer/requirements-tools.txt"
        lock.write_text("example==1.0\n")
        venv = self.root / ".venv"
        venv.mkdir()
        sentinel = venv / "owner-state"
        sentinel.write_text("preserve")
        for receipt in [None, "{}", "invalid json"]:
            if receipt is not None:
                (venv / ".hapatchy-environment.json").write_text(receipt)
            with (
                self.subTest(marker=receipt),
                self.assertRaisesRegex(RuntimeError, "restart"),
            ):
                self.env.prepare_venv(self.root, ".venv", lock.name, {}, live=True)
            self.assertEqual(sentinel.read_text(), "preserve")


if __name__ == "__main__":
    unittest.main()
