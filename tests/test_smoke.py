"""Smoke tests for subagent-budget-team. stdlib only (unittest)."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

CLI = [sys.executable, "-m", "subagent_budget_team.cli"]
SRC = Path(__file__).resolve().parent.parent / "src"


def _env(tmp: Path) -> dict:
    env = dict(os.environ)
    env["SBT_HOME"] = str(tmp)
    env["PYTHONPATH"] = str(SRC) + os.pathsep + env.get("PYTHONPATH", "")
    return env


class SmokeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sbt-test-"))
        self.env = _env(self.tmp)

    def run_cli(self, *args: str):
        return subprocess.run(CLI + list(args), capture_output=True,
                              text=True, env=self.env)

    def test_01_pool_create_and_list(self):
        r = self.run_cli("pool", "create", "--name", "ci-nightly",
                         "--limit-usd", "25")
        self.assertEqual(r.returncode, 0, r.stderr)
        r = self.run_cli("pool", "list")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("ci-nightly", r.stdout)

    def test_02_quota_set(self):
        self.run_cli("pool", "create", "--name", "team", "--limit-usd", "100")
        r = self.run_cli("quota", "set", "--pool", "team",
                         "--agent", "coder-1", "--limit-usd", "10")
        self.assertEqual(r.returncode, 0, r.stderr)
        r = self.run_cli("pool", "list", "--json")
        pools = json.loads(r.stdout)
        self.assertIn("coder-1", pools[0]["agents"])

    def test_03_spend_within_budget_check_ok(self):
        self.run_cli("pool", "create", "--name", "p", "--limit-usd", "50")
        r = self.run_cli("spend", "--pool", "p", "--agent", "a",
                         "--tokens", "1000", "--usd", "2.50")
        self.assertEqual(r.returncode, 0, r.stderr)
        r = self.run_cli("check")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("OK", r.stdout)

    def test_04_pool_overspend_check_fails(self):
        self.run_cli("pool", "create", "--name", "p", "--limit-usd", "5")
        self.run_cli("spend", "--pool", "p", "--agent", "a", "--usd", "6.01")
        r = self.run_cli("check")
        self.assertEqual(r.returncode, 1)
        self.assertIn("OVER BUDGET", r.stdout)

    def test_05_agent_quota_overspend_check_fails(self):
        self.run_cli("pool", "create", "--name", "p", "--limit-usd", "100")
        self.run_cli("quota", "set", "--pool", "p", "--agent", "a",
                     "--limit-usd", "1")
        self.run_cli("spend", "--pool", "p", "--agent", "a", "--usd", "1.50")
        r = self.run_cli("check")
        self.assertEqual(r.returncode, 1)
        self.assertIn("agent_over", r.stdout + self.run_cli(
            "check", "--json").stdout)

    def test_06_kill_switch_breaks_check(self):
        self.run_cli("pool", "create", "--name", "p", "--limit-usd", "50")
        self.run_cli("spend", "--pool", "p", "--agent", "a", "--usd", "1")
        r = self.run_cli("check")
        self.assertEqual(r.returncode, 0)
        r = self.run_cli("kill", "--pool", "p")
        self.assertEqual(r.returncode, 0, r.stderr)
        r = self.run_cli("check")
        self.assertEqual(r.returncode, 1)
        self.assertIn("killed", r.stdout.lower())

    def test_07_kill_rejects_new_spend(self):
        self.run_cli("pool", "create", "--name", "p", "--limit-usd", "50")
        self.run_cli("kill", "--pool", "p")
        r = self.run_cli("spend", "--pool", "p", "--agent", "a", "--usd", "1")
        self.assertNotEqual(r.returncode, 0)

    def test_08_release_restores_ok(self):
        self.run_cli("pool", "create", "--name", "p", "--limit-usd", "50")
        self.run_cli("kill", "--pool", "p")
        self.run_cli("release", "--pool", "p")
        r = self.run_cli("check")
        self.assertEqual(r.returncode, 0)

    def test_09_duplicate_pool_rejected(self):
        self.run_cli("pool", "create", "--name", "p", "--limit-usd", "1")
        r = self.run_cli("pool", "create", "--name", "p", "--limit-usd", "1")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("already exists", r.stderr)

    def test_10_negative_limit_rejected(self):
        r = self.run_cli("pool", "create", "--name", "p",
                         "--limit-usd", "-5")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("positive", r.stderr)

    def test_11_check_json_output(self):
        self.run_cli("pool", "create", "--name", "p", "--limit-tokens", "100")
        self.run_cli("spend", "--pool", "p", "--agent", "a", "--tokens", "150")
        r = self.run_cli("check", "--json")
        self.assertEqual(r.returncode, 1)
        data = json.loads(r.stdout)
        self.assertEqual(data[0]["kind"], "pool_over")
        self.assertEqual(data[0]["pool"], "p")

    def test_12_version(self):
        r = self.run_cli("--version")
        self.assertEqual(r.returncode, 0)
        self.assertIn("0.1.0", r.stdout)


if __name__ == "__main__":
    unittest.main()
