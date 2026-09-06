"""Boundary and failure tests for the custom operational code."""

import io
import json
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import backup
import common
import guard
import initialize
from common import API, GIB
from install_jobs import updated_crontab
from preflight import validate_policy, validate_settings
from render_cloudflare import payloads

POLICY = {"stop_free_gib": 25, "warning_free_gib": 40, "media_budget_gib": 150}


class BudgetTests(unittest.TestCase):
    def assess(self, free, used=0, remaining=0):
        return guard.assess(free * GIB, used * GIB, remaining * GIB, POLICY)

    def test_stop_boundary(self):
        self.assertEqual(self.assess(25)[0], "stop")
        self.assertEqual(self.assess(25 + 1 / GIB)[0], "warning")

    def test_warning_boundary(self):
        self.assertEqual(self.assess(40)[0], "warning")
        self.assertEqual(self.assess(40 + 1 / GIB)[0], "ok")

    def test_queued_payload_must_leave_reserve(self):
        self.assertEqual(self.assess(100, remaining=75)[0], "ok")
        self.assertEqual(self.assess(100, remaining=75 + 1 / GIB)[0], "stop")

    def test_soft_budget_does_not_delete_or_stop(self):
        self.assertEqual(self.assess(50, used=151), ("warning", "media_above_soft_budget"))

    def test_invalid_measurement_fails_closed(self):
        self.assertEqual(self.assess(-1)[0], "stop")

    def test_unlimited_downloads_rejected(self):
        prefs = {
            "dl_limit": 0,
            "alt_dl_limit": 1,
            "queueing_enabled": True,
            "dont_count_slow_torrents": False,
            "max_active_downloads": 2,
        }
        self.assertFalse(
            guard.bounded_preferences(
                prefs, {"max_download_bytes_per_second": 20, "max_active_downloads": 2}
            )
        )


class HoldTests(unittest.TestCase):
    def test_latch_written_before_stopping(self):
        with tempfile.TemporaryDirectory() as td:
            latch = Path(td) / "hold.json"
            with patch.object(guard, "LATCH", latch), patch.object(guard, "stop_services") as stop:
                stop.side_effect = lambda: self.assertTrue(latch.exists())
                guard.trip("disk")
                self.assertEqual(json.loads(latch.read_text())["reason"], "disk")

    def test_latch_write_failure_still_stops(self):
        with (
            patch.object(guard, "write_private", side_effect=OSError("disk full")),
            patch.object(guard, "stop_services") as stop,
            patch.object(guard, "LATCH", Path("/nonexistent/hold.json")),
        ):
            with self.assertRaises(OSError):
                guard.trip("disk")
            stop.assert_called_once()

    def test_api_failure_still_stops_containers(self):
        with (
            patch.object(guard, "API", side_effect=RuntimeError("offline")),
            patch.object(guard, "compose") as compose,
            patch.object(guard, "running_services", return_value=[]),
        ):
            guard.stop_services()
            compose.assert_called_once()
            self.assertIn("stop", compose.call_args.args)

    def test_existing_hold_never_auto_resumes(self):
        with tempfile.TemporaryDirectory() as td:
            latch = Path(td) / "hold.json"
            latch.write_text("{}")
            with (
                patch.object(guard, "LATCH", latch),
                patch.object(guard, "STATUS", Path(td) / "status.json"),
                patch.object(guard, "running_services", return_value=[]),
                patch.object(guard, "sample") as sample,
            ):
                self.assertEqual(guard.check()["level"], "held")
                sample.assert_not_called()
                self.assertTrue(latch.exists())


class CronTests(unittest.TestCase):
    def test_install_is_idempotent_and_preserves_existing_jobs(self):
        existing = "MAILTO=\n5 * * * * /existing/job\n"
        result = updated_crontab(existing, "/srv/anime-stack")
        self.assertIn("/existing/job", result)
        self.assertEqual(updated_crontab(result, "/srv/anime-stack"), result)

    def test_malformed_block_rejected(self):
        with self.assertRaises(ValueError):
            updated_crontab("# BEGIN anime-stack managed jobs\n", "/tmp/stack")

    def test_cron_percent_rejected(self):
        with self.assertRaises(ValueError):
            updated_crontab("", "/tmp/%bad")


class AuthenticationTests(unittest.TestCase):
    def test_empty_login_response_requires_protected_endpoint_check(self):
        api = object.__new__(API)
        api.service = "qbittorrent"
        api.credentials = {"username": "test", "password": "test"}
        with (
            patch.object(api, "request", return_value=""),
            patch.object(api, "preferences") as preferences,
        ):
            self.assertIs(api.login(), api)
            preferences.assert_called_once()

    def test_empty_response_without_session_is_not_success(self):
        api = object.__new__(API)
        api.service = "qbittorrent"
        api.credentials = {}
        with (
            patch.object(api, "request", return_value=""),
            patch.object(api, "preferences", side_effect=RuntimeError("unauthenticated")),
        ):
            with self.assertRaises(RuntimeError):
                api.login()


class CloudflareTests(unittest.TestCase):
    def test_every_origin_requires_its_own_access_audience(self):
        settings = json.loads(
            (Path(__file__).resolve().parents[1] / "cloudflare/settings.example.json").read_text()
        )
        plan = payloads(settings)
        ingress = plan["05-tunnel-configuration.json"]["config"]["ingress"]
        self.assertEqual(ingress[-1], {"service": "http_status:404"})
        for route, audience in zip(
            ingress[:2], [settings["autobangumi_aud"], settings["qbittorrent_aud"]]
        ):
            self.assertTrue(route["originRequest"]["access"]["required"])
            self.assertEqual(route["originRequest"]["access"]["audTag"], [audience])

    def test_host_outside_zone_rejected(self):
        settings = json.loads(
            (Path(__file__).resolve().parents[1] / "cloudflare/settings.example.json").read_text()
        )
        settings["qbittorrent_hostname"] = "qb.another-domain.com"
        with self.assertRaises(ValueError):
            payloads(settings)


class RestoreTests(unittest.TestCase):
    def archive(self, path, extra=None):
        with tarfile.open(path, "w:gz") as out:
            for name in [
                "compose.yaml",
                ".env",
                "runtime/policy.json",
                "runtime/secrets/credentials.json",
            ] + ([extra] if extra else []):
                data = (
                    b"DATA_DIR=/old/state\nMEDIA_DIR=/old/media\nCOMPOSE_PROJECT_NAME=original\n"
                    if name == ".env"
                    else b"{}"
                )
                info = tarfile.TarInfo(name)
                info.size = len(data)
                out.addfile(info, io.BytesIO(data))

    def test_restore_wont_overwrite_directory(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ValueError):
                backup.restore("unused", td)

    def test_path_traversal_rejected_before_extraction(self):
        with tempfile.TemporaryDirectory() as td:
            archive = Path(td) / "test.tar.gz"
            self.archive(archive, "../escape")
            target = Path(td) / "restore"
            with self.assertRaises(ValueError):
                backup.restore(archive, target)
            self.assertFalse(target.exists())

    def test_valid_backup_can_be_restored(self):
        with tempfile.TemporaryDirectory() as td:
            archive = Path(td) / "test.tar.gz"
            self.archive(archive)
            target = Path(td) / "restore"
            backup.restore(archive, target)
            self.assertTrue((target / "runtime/secrets/credentials.json").is_file())
            self.assertTrue((target / "runtime/ops/hold.json").is_file())
            config = common.dotenv(target / ".env")
            self.assertEqual(config["DATA_DIR"], "./runtime")
            self.assertEqual(config["COMPOSE_PROJECT_NAME"], "anime-stack-recovery")

    def test_restore_rejects_links_before_extraction(self):
        with tempfile.TemporaryDirectory() as td:
            archive = Path(td) / "test.tar.gz"
            self.archive(archive)
            # Build an otherwise valid archive with a malicious symlink.
            other = Path(td) / "with-link.tar.gz"
            with tarfile.open(archive) as src, tarfile.open(other, "w:gz") as dst:
                for member in src.getmembers():
                    dst.addfile(member, src.extractfile(member))
                link = tarfile.TarInfo("runtime/secrets/escape")
                link.type = tarfile.SYMTYPE
                link.linkname = "/etc/passwd"
                dst.addfile(link)
            target = Path(td) / "restore"
            with self.assertRaises(ValueError):
                backup.restore(other, target)
            self.assertFalse(target.exists())


class ConfigurationTests(unittest.TestCase):
    def config(self):
        return common.dotenv(Path(__file__).resolve().parents[1] / ".env.example")

    def test_default_configuration_is_valid(self):
        validate_settings(self.config())

    def test_public_subnet_is_rejected(self):
        value = self.config()
        value["NETWORK_SUBNET"] = "203.0.113.0/24"
        with self.assertRaises(ValueError):
            validate_settings(value)

    def test_address_outside_subnet_is_rejected(self):
        value = self.config()
        value["PROXY_ADDRESS"] = "192.168.2.4"
        with self.assertRaises(ValueError):
            validate_settings(value)

    def test_duplicate_port_is_rejected(self):
        value = self.config()
        value["QB_WEB_PORT"] = value["PEER_PORT"]
        with self.assertRaises(ValueError):
            validate_settings(value)

    def test_hostname_injection_is_rejected(self):
        value = self.config()
        value["QB_PUBLIC_HOST"] = "qb.example.com;*"
        with self.assertRaises(ValueError):
            validate_settings(value)

    def test_policy_with_invalid_threshold_order_is_rejected(self):
        value = json.loads(
            (Path(__file__).resolve().parents[1] / "policy.example.json").read_text()
        )
        value["warning_free_gib"] = value["stop_free_gib"]
        with self.assertRaises(ValueError):
            validate_policy(value)

    def test_dotenv_rejects_shell_expansion_and_duplicate_keys(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / ".env"
            for text in ("PATH=$(id)\n", "PUID=1000\nPUID=1001\n"):
                path.write_text(text)
                with self.assertRaises(ValueError):
                    common.dotenv(path)

    def test_cron_projects_do_not_replace_one_another(self):
        first = updated_crontab("", "/srv/one", project="one", with_backup=False)
        both = updated_crontab(first, "/srv/two", project="two", with_backup=False)
        self.assertIn("/srv/one/scripts/guard.py", both)
        self.assertIn("/srv/two/scripts/guard.py", both)
        self.assertNotIn("backup.py", both)


class InitializationTests(unittest.TestCase):
    def test_initialization_preserves_credentials_and_refuses_orphaned_state(self):
        source = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for name in (".env.example", "policy.example.json"):
                (root / name).write_text((source / name).read_text())
            with (
                patch.object(common, "ROOT", root),
                patch.object(initialize, "ROOT", root),
                patch.object(initialize.os, "getuid", return_value=1000),
                patch.object(initialize.os, "getgid", return_value=1000),
            ):
                initialize.initialize()
                path = root / "runtime/secrets/credentials.json"
                first = path.read_bytes()
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                initialize.initialize()
                self.assertEqual(path.read_bytes(), first)
                path.unlink()
                with self.assertRaises(RuntimeError):
                    initialize.initialize()


if __name__ == "__main__":
    unittest.main()
