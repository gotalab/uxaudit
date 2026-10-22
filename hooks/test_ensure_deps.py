"""Exercise the SessionStart hook in an isolated PATH without installing anything."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class EnsureDepsTests(unittest.TestCase):
    def run_hook(self, version, cached, node_exit=0):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            data = root / "data"
            data.mkdir()
            calls = root / "calls"

            def command(name, body):
                path = bin_dir / name
                path.write_text("#!/bin/bash\n" + body + "\n")
                path.chmod(0o755)

            for name in ("mkdir", "cp", "diff"):
                (bin_dir / name).symlink_to(shutil.which(name))
            for name in ("python3", "npm", "npx"):
                command(name, f'printf "%s\\n" "{name} $*" >> "$CALLS"')
            if version is not None:
                command("node", 'printf "%s\\n" "node $*" >> "$CALLS"\n'
                        'printf "%s\\n" "$TEST_NODE_VERSION"\n'
                        f"exit {node_exit}")
            if cached:
                for package in ("playwright", "axe-core"):
                    (data / "node_modules" / package).mkdir(parents=True)
                shutil.copyfile(ROOT / "skills/uxaudit/package.json", data / "package.json")
            env = {
                **os.environ,
                "PATH": str(bin_dir),
                "CLAUDE_PLUGIN_ROOT": str(ROOT),
                "CLAUDE_PLUGIN_DATA": str(data),
                "TEST_NODE_VERSION": version or "",
                "CALLS": str(calls),
            }
            result = subprocess.run(
                ["/bin/bash", str(ROOT / "hooks/ensure-deps.sh")],
                env=env, capture_output=True, text=True, timeout=5,
            )
            recorded = calls.read_text().splitlines() if calls.exists() else []
            return result, recorded

    def test_missing_or_unsupported_node_warns_without_installing(self):
        for cached in (False, True):
            for version in (None, "v20.20.0", "v22.23.4", "v26.12.1",
                            "v24.21.9", "v24.22.0", "v24.22.1-rc.1", "invalid"):
                with self.subTest(version=version, cached=cached):
                    result, calls = self.run_hook(version, cached)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn("WARN", result.stderr)
                    self.assertIn("24.22.1+ (24.x)", result.stderr)
                    self.assertEqual(calls, [] if version is None else ["node --version"])

    def test_node_version_command_failure_warns_without_installing(self):
        for cached in (False, True):
            with self.subTest(cached=cached):
                result, calls = self.run_hook("v24.22.1", cached, node_exit=1)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("WARN", result.stderr)
                self.assertEqual(calls, ["node --version"])

    def test_supported_node_installs_only_when_cache_is_missing(self):
        for cached in (False, True):
            for version in ("v24.22.1", "v24.22.2", "v24.23.0"):
                with self.subTest(version=version, cached=cached):
                    result, calls = self.run_hook(version, cached)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertNotIn("WARN", result.stderr)
                    expected = ["node --version"]
                    if cached:
                        self.assertEqual(result.stderr, "")
                    else:
                        expected += ["npm ci --silent --no-audit --no-fund",
                                     "npx playwright install chromium"]
                        self.assertIn("OK: Playwright dependencies ready", result.stderr)
                    self.assertEqual(calls, expected)


if __name__ == "__main__":
    unittest.main()
