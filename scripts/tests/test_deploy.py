"""Deployment orchestration tests; no Docker daemon, real .env or database needed.

Run: python3 -m unittest discover -s scripts/tests -v
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FAKE_DOCKER = r'''
import json, os, sys
args = sys.argv[1:]
with open(os.environ["DOCKER_TEST_LOG"], "a") as stream:
    stream.write(json.dumps({"args": args, "parallel": os.getenv("COMPOSE_PARALLEL_LIMIT"),
                             "bake": os.getenv("COMPOSE_BAKE")}) + "\n")
if args[:2] == ["image", "inspect"]:
    if "\n" in args[-1]:
        sys.exit(2)
    if "--format" in args:
        print("1" if args[-1] == "shirin-backend:latest" and not os.getenv("DOCKER_TEST_OLD_IMAGE") else "")
    sys.exit(1 if args[-1] == os.getenv("DOCKER_TEST_MISSING_IMAGE") else 0)
if args[0] == "ps":
    for service in os.getenv("DOCKER_TEST_OLD_SERVICES", "").split(","):
        if service and "label=com.docker.compose.service=" + service in args:
            print("old-" + service)
if args[0] == "inspect":
    if os.getenv("DOCKER_TEST_MISSING_GATEWAY"):
        sys.exit(1)
    print("gateway-id" if args[2] == "{{.Id}}" else "existing-network")
if args[0] == "compose":
    if "--images" in args:
        images = ["shirin-backend:latest", "shirin-backend:latest", "postgres:16-alpine",
                  "shirin-user_panel", "shirin-admin_panel", "shirin-superadmin_panel"]
        if "deploy/docker-compose.cloud.yml" in args:
            images.append("caddy:2-alpine")
        if args[-1] == "backend":
            images = ["shirin-backend:latest", "postgres:16-alpine", "shirin-backend:latest"]
        print("\n".join(images))
    if "build" in args and args[-1] == os.getenv("DOCKER_TEST_FAIL_BUILD"):
        sys.exit(31)
    if "pull" in args and os.getenv("DOCKER_TEST_FAIL_PULL"):
        sys.exit(32)
    if "up" in args and "--exit-code-from" in args and os.getenv("DOCKER_TEST_FAIL_MIGRATE"):
        sys.exit(42)
'''


class DeploymentTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "deploy").mkdir()
        (self.root / "bin").mkdir()
        for script in ("up.sh", "down.sh"):
            shutil.copy(ROOT / script, self.root / script)
            shutil.copy(ROOT / "deploy" / script, self.root / "deploy" / script)
        self.env_file = self.root / ".env"
        self.env_file.write_text(
            "SHIRIN_USER_BOT_TOKEN=fake-user\nSHIRIN_ADMIN_BOT_TOKEN=fake-admin\n"
            "SHIRIN_SUPERADMIN_BOT_TOKEN=fake-superadmin\n"
        )
        self.docker = self.root / "bin/docker"
        self.docker.write_text(f"#!{sys.executable}\n{FAKE_DOCKER}")
        self.docker.chmod(0o700)
        self.log = self.root / "docker.jsonl"

    def run_script(self, script, *args, **settings):
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(("SHIRIN_", "COMPOSE_", "DOCKER_TEST_"))}
        env.update(settings)
        env["PATH"] = str(self.root / "bin") + os.pathsep + env.get("PATH", "")
        env["DOCKER_TEST_LOG"] = str(self.log)
        result = subprocess.run(
            ["bash", str(self.root / script), *args],
            cwd=self.root, env=env, capture_output=True, text=True, timeout=15,
        )
        entries = [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []
        return result, entries

    def run_up(self, *args, **settings):
        return self.run_script("up.sh", *args, **settings)

    def run_down(self, *args, **settings):
        return self.run_script("down.sh", *args, **settings)

    def test_builds_are_serial_and_finish_before_migration_or_start(self):
        result, entries = self.run_up(COMPOSE_PARALLEL_LIMIT="8", COMPOSE_BAKE="true")
        self.assertEqual(result.returncode, 0, result.stderr)
        commands = [entry["args"] for entry in entries]
        builds = [cmd for cmd in commands if "build" in cmd]
        self.assertEqual([cmd[-1] for cmd in builds], ["backend", "user_panel", "admin_panel", "superadmin_panel"])
        starts = [cmd for cmd in commands if "up" in cmd]
        self.assertLess(commands.index(builds[-1]), commands.index(starts[0]))
        self.assertEqual(starts[0][-1], "postgres")
        self.assertEqual(starts[1][-1], "migrate")
        self.assertIn("backend", starts[2])
        self.assertTrue(all("--no-build" in cmd and "--build" not in cmd for cmd in starts))
        self.assertTrue(all(cmd[cmd.index("--pull") + 1] == "never" for cmd in starts))
        self.assertEqual([cmd[cmd.index("pull"):] for cmd in commands if "pull" in cmd], [["pull", "--policy", "missing", "postgres"]])
        self.assertTrue(all(entry["parallel"] == "1" and entry["bake"] == "false" for entry in entries))

    def test_failed_build_leaves_services_untouched(self):
        result, entries = self.run_up("--compact", DOCKER_TEST_FAIL_BUILD="admin_panel", DOCKER_TEST_OLD_SERVICES="user_bot")
        self.assertEqual(result.returncode, 31)
        self.assertFalse(any("up" in entry["args"] for entry in entries))
        self.assertFalse(any(entry["args"][0] in {"stop", "rm"} for entry in entries))

    def test_failed_stock_image_pull_leaves_services_untouched(self):
        result, entries = self.run_up("--compact", DOCKER_TEST_FAIL_PULL="1", DOCKER_TEST_OLD_SERVICES="user_bot")
        self.assertEqual(result.returncode, 32)
        self.assertFalse(any("up" in entry["args"] for entry in entries))
        self.assertFalse(any(entry["args"][0] in {"stop", "rm"} for entry in entries))

    def test_failed_migration_prevents_application_start(self):
        result, entries = self.run_up("--compact", DOCKER_TEST_FAIL_MIGRATE="1", DOCKER_TEST_OLD_SERVICES="user_bot")
        self.assertEqual(result.returncode, 42)
        self.assertEqual([entry["args"][-1] for entry in entries if "up" in entry["args"]], ["postgres", "migrate"])
        self.assertFalse(any(entry["args"][0] in {"stop", "rm"} for entry in entries))
        self.assertFalse(any("--remove-orphans" in entry["args"] for entry in entries))

    def test_no_build_checks_unique_images_and_never_pulls(self):
        result, entries = self.run_up("--shared", "--no-build")
        self.assertEqual(result.returncode, 0, result.stderr)
        commands = [entry["args"] for entry in entries]
        self.assertFalse(any("build" in cmd for cmd in commands))
        self.assertFalse(any("pull" in cmd for cmd in commands))
        inspected = [cmd[-1] for cmd in commands if cmd[:2] == ["image", "inspect"]]
        self.assertEqual(len(inspected), 5)
        self.assertEqual(len(inspected), len(set(inspected)))
        self.assertTrue(all(cmd[cmd.index("--pull") + 1] == "never" for cmd in commands if "up" in cmd))
        self.assertIn("git pull", result.stdout)

    def test_missing_image_does_not_change_containers(self):
        result, entries = self.run_up("--no-build", DOCKER_TEST_MISSING_IMAGE="shirin-admin_panel")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Missing local image: shirin-admin_panel", result.stderr)
        self.assertFalse(any("up" in entry["args"] or "build" in entry["args"] for entry in entries))

    def test_cloud_option_combines_with_no_build(self):
        result, entries = self.run_up("--no-build", "--cloud", "--compact")
        self.assertEqual(result.returncode, 0, result.stderr)
        commands = [entry["args"] for entry in entries]
        self.assertIn(["image", "inspect", "caddy:2-alpine"], commands)
        self.assertTrue(all("deploy/docker-compose.cloud.yml" in cmd for cmd in commands if cmd[0] == "compose"))
        self.assertEqual([cmd for cmd in commands if "up" in cmd][-1][-1], "gateway")
        self.assertTrue(all("deploy/docker-compose.compact.yml" in cmd for cmd in commands if cmd[0] == "compose"))

    def test_cloud_pulls_only_stock_runtime_images(self):
        result, entries = self.run_up("--cloud")
        self.assertEqual(result.returncode, 0, result.stderr)
        commands = [entry["args"] for entry in entries]
        pulls = [cmd[cmd.index("pull"):] for cmd in commands if "pull" in cmd]
        self.assertEqual(pulls, [["pull", "--policy", "missing", "postgres", "gateway"]])
        self.assertTrue(all(cmd[cmd.index("--pull") + 1] == "never" for cmd in commands if "up" in cmd))

    def test_switch_to_compact_stops_old_pollers_only_after_migration(self):
        old_services = ["worker", "user_bot", "admin_bot", "superadmin_bot", "bot"]
        result, entries = self.run_up("--compact", DOCKER_TEST_OLD_SERVICES=",".join(old_services))
        self.assertEqual(result.returncode, 0, result.stderr)
        commands = [entry["args"] for entry in entries]
        migrate_index = next(index for index, cmd in enumerate(commands) if "--exit-code-from" in cmd)
        runtime_index = next(index for index, cmd in enumerate(commands) if "up" in cmd and "backend" in cmd)
        for service in old_services:
            stop_index = commands.index(["stop", "old-" + service])
            remove_index = commands.index(["rm", "old-" + service])
            self.assertLess(migrate_index, stop_index)
            self.assertLess(stop_index, remove_index)
            self.assertLess(remove_index, runtime_index)
        runtime = commands[runtime_index]
        self.assertIn("workers", runtime)
        self.assertFalse(any(service in runtime for service in old_services))
        self.assertEqual([cmd for cmd in commands if "--remove-orphans" in cmd], [runtime])
        self.assertTrue(all("label=com.docker.compose.project=shirin" in cmd for cmd in commands if cmd[0] == "ps"))

    def test_switch_from_compact_stops_old_workers(self):
        self.env_file.write_text(self.env_file.read_text() + "SHIRIN_COMPACT_WORKERS=true\n")
        result, entries = self.run_up("--no-build", SHIRIN_COMPACT_WORKERS="false", DOCKER_TEST_OLD_SERVICES="workers,bot")
        self.assertEqual(result.returncode, 0, result.stderr)
        commands = [entry["args"] for entry in entries]
        self.assertIn(["stop", "old-workers"], commands)
        self.assertIn(["stop", "old-bot"], commands)
        runtime = [cmd for cmd in commands if "up" in cmd][-1]
        self.assertLess(commands.index(["rm", "old-workers"]), commands.index(runtime))
        self.assertLess(commands.index(["rm", "old-bot"]), commands.index(runtime))
        self.assertNotIn("workers", runtime)
        self.assertTrue(all(service in runtime for service in ["worker", "user_bot", "admin_bot", "superadmin_bot"]))

    def test_compact_mode_can_be_persisted_in_env(self):
        self.env_file.write_text(self.env_file.read_text() + "SHIRIN_COMPACT_WORKERS=true\n")
        original = self.env_file.read_text()
        result, entries = self.run_up("--no-build")
        self.assertEqual(result.returncode, 0, result.stderr)
        runtime = [entry["args"] for entry in entries if "up" in entry["args"]][-1]
        self.assertIn("workers", runtime)
        self.assertEqual(self.env_file.read_text(), original)

    def test_compact_requires_an_image_with_compact_worker_code(self):
        result, entries = self.run_up("--compact", "--no-build", DOCKER_TEST_OLD_IMAGE="1", DOCKER_TEST_OLD_SERVICES="user_bot")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("does not support compact workers", result.stderr)
        self.assertFalse(any("up" in entry["args"] or entry["args"][0] in {"stop", "rm"} for entry in entries))

    def test_invalid_options_fail_before_docker(self):
        result, entries = self.run_up("--shared", "--cloud")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(entries, [])

    def test_duplicate_tokens_fail_before_docker(self):
        self.env_file.write_text(self.env_file.read_text().replace("fake-admin", "fake-user"))
        result, entries = self.run_up()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(entries, [])

    def test_requested_gateway_must_exist_before_build(self):
        result, entries = self.run_up(SHIRIN_SHARED_GATEWAY_CONTAINER="kulcha-gateway", DOCKER_TEST_MISSING_GATEWAY="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any("build" in entry["args"] or "up" in entry["args"] for entry in entries))

    def test_only_explicit_gateway_is_connected_after_start(self):
        result, entries = self.run_up(SHIRIN_SHARED_GATEWAY_CONTAINER="kulcha-gateway")
        self.assertEqual(result.returncode, 0, result.stderr)
        commands = [entry["args"] for entry in entries]
        connect = ["network", "connect", "shirin_gateway", "kulcha-gateway"]
        self.assertIn(connect, commands)
        self.assertLess(commands.index([cmd for cmd in commands if "up" in cmd][-1]), commands.index(connect))

    def test_switch_uses_selected_compose_project(self):
        self.env_file.write_text(self.env_file.read_text() + "COMPOSE_PROJECT_NAME=shirin-staging\n")
        result, entries = self.run_up("--compact", "--no-build")
        self.assertEqual(result.returncode, 0, result.stderr)
        inspected = [entry["args"] for entry in entries if entry["args"][0] == "ps"]
        self.assertTrue(inspected)
        self.assertTrue(all("label=com.docker.compose.project=shirin-staging" in args for args in inspected))

    def test_down_stops_all_worker_modes_and_preserves_volumes(self):
        result, entries = self.run_down("--compact", "--cloud")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(entries), 1)
        command = entries[0]["args"]
        self.assertIn("deploy/docker-compose.compact.yml", command)
        self.assertIn("deploy/docker-compose.cloud.yml", command)
        self.assertEqual(command[command.index("--profile") + 1], "*")
        self.assertEqual(command[-2:], ["down", "--remove-orphans"])
        self.assertNotIn("--volumes", command)
        self.assertNotIn("-v", command)

    def test_down_reads_persistent_flags_without_modifying_env(self):
        self.env_file.write_text(self.env_file.read_text() + "SHIRIN_SHARED_GATEWAY=false\nSHIRIN_COMPACT_WORKERS=true\n")
        original = self.env_file.read_text()
        result, entries = self.run_down()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("deploy/docker-compose.compact.yml", entries[0]["args"])
        self.assertIn("deploy/docker-compose.cloud.yml", entries[0]["args"])
        self.assertEqual(self.env_file.read_text(), original)

    def test_down_can_override_persistent_flags(self):
        self.env_file.write_text(self.env_file.read_text() + "SHIRIN_SHARED_GATEWAY=false\nSHIRIN_COMPACT_WORKERS=true\n")
        result, entries = self.run_down("--shared", SHIRIN_COMPACT_WORKERS="false")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("deploy/docker-compose.compact.yml", entries[0]["args"])
        self.assertNotIn("deploy/docker-compose.cloud.yml", entries[0]["args"])

    def test_down_rejects_conflicting_gateway_flags_before_docker(self):
        result, entries = self.run_down("--shared", "--cloud")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(entries, [])


if __name__ == "__main__":
    unittest.main()
