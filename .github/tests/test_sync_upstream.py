import importlib.util
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "sync_upstream.py"
spec = importlib.util.spec_from_file_location("sync_upstream", SCRIPT)
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.previous = Path.cwd()
        os.chdir(self.directory.name)
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.com")
        self.write(".github/workflows/ci.yml", "original CI\n")
        self.write("DEPLOYMENT.md", "original deployment\n")
        self.write("app.py", "original code\n")
        self.commit("base")
        self.git("branch", "upstream")
        self.write(".github/workflows/ci.yml", "our GitOps CI\n")
        self.write("DEPLOYMENT.md", "our manual production\n")
        self.commit("local CI")
        self.local_head = self.git("rev-parse", "HEAD")

    def tearDown(self):
        os.chdir(self.previous)
        self.directory.cleanup()

    def git(self, *args):
        return subprocess.check_output(["git", *args], stderr=subprocess.DEVNULL, text=True).strip()

    def write(self, path, content):
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)

    def commit(self, message):
        self.git("add", ".")
        self.git("commit", "-m", message)
        return self.git("rev-parse", "HEAD")

    def upstream(self):
        self.git("checkout", "upstream")
        self.write("app.py", "new developer code\n")
        self.write(".github/workflows/ci.yml", "old server CI\n")
        self.write(".github/workflows/extra.yml", "must not execute\n")
        self.write("DEPLOYMENT.md", "old server instructions\n")
        revision = self.commit("developer changes")
        self.git("checkout", "main")
        return revision

    def test_merge_preserves_ci_and_ancestry_and_is_idempotent(self):
        revision = self.upstream()
        self.assertTrue(sync.merge_upstream(revision))
        self.assertEqual(Path("app.py").read_text(), "new developer code\n")
        self.assertEqual(Path(".github/workflows/ci.yml").read_text(), "our GitOps CI\n")
        self.assertEqual(Path("DEPLOYMENT.md").read_text(), "our manual production\n")
        self.assertFalse(Path(".github/workflows/extra.yml").exists())
        self.git("merge-base", "--is-ancestor", revision, "HEAD")
        self.assertFalse(sync.merge_upstream(revision))
        self.assertEqual(self.git("status", "--porcelain"), "")

    def test_code_conflict_aborts_without_overwriting_local_code(self):
        revision = self.upstream()
        self.write("app.py", "our independent fix\n")
        self.commit("local fix")
        before = self.git("rev-parse", "HEAD")
        with self.assertRaisesRegex(RuntimeError, "manual merge"):
            sync.merge_upstream(revision)
        self.assertEqual(self.git("rev-parse", "HEAD"), before)
        self.assertEqual(Path("app.py").read_text(), "our independent fix\n")
        self.assertEqual(self.git("status", "--porcelain"), "")

    def test_dirty_checkout_is_not_modified(self):
        revision = self.upstream()
        self.write("app.py", "unsaved work\n")
        with self.assertRaisesRegex(RuntimeError, "local changes"):
            sync.merge_upstream(revision)
        self.assertEqual(Path("app.py").read_text(), "unsaved work\n")


if __name__ == "__main__":
    unittest.main()
