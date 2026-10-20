import importlib.util
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "skills/gh-workflow-conventions/scripts/check_html_fragments.py"
spec = importlib.util.spec_from_file_location("html_fragments", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
BASE = "https://example.org/manual/"


class FragmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def run_check(self):
        return module.check(self.root, BASE)

    def test_case_sensitive_cross_page_fragment(self):
        source = self.write("configuration/index.html", '<a href="../strategies/#graph-partition-sweeps">partition</a>')
        self.write("strategies/index.html", '<h2 id="Graph-partition-sweeps">Partition</h2>')
        self.assertFalse(self.run_check()["passed"])
        source.write_text('<a href="../strategies/#Graph-partition-sweeps">partition</a>')
        self.assertTrue(self.run_check()["passed"])

    def test_encoded_unicode_and_legacy_named_anchor(self):
        self.write("index.html", '<a href="#%CE%B1%20%26%20%CE%B2">one</a><a href="#legacy">two</a><h2 id="α &amp; β"></h2><a name="legacy"></a>')
        self.assertEqual(self.run_check()["checked_fragments"], 2)
        self.assertTrue(self.run_check()["passed"])

    def test_owned_absolute_link_and_directory_route(self):
        self.write("index.html", '<a href="https://example.org/manual/topic?q=x#Title">topic</a>')
        self.write("topic/index.html", '<h2 id="Title"></h2>')
        self.assertTrue(self.run_check()["passed"])

    def test_missing_page_and_missing_anchor(self):
        self.write("index.html", '<a href="missing/#Title">missing</a><a href="other.html#Title">other</a>')
        self.write("other.html", '<h2 id="Different"></h2>')
        self.assertEqual([x["reason"] for x in self.run_check()["broken"]],
                         ["missing HTML page", "missing case-sensitive anchor"])

    def test_external_other_site_path_and_non_html_are_out_of_scope(self):
        self.write("index.html", '<a href="https://other.org/#X">external</a><a href="/other/#X">other owner</a><a href="paper.pdf#page=2">PDF</a>')
        result = self.run_check()
        self.assertTrue(result["passed"])
        self.assertEqual(result["skipped_external_or_non_html"], 3)

    def test_empty_href_top_and_native_text_fragments(self):
        self.write("index.html", '<a href>empty</a><a href="">empty</a><a href="#">empty</a><a href="#top">top</a><a href="#:~:text=word">text</a><a href="#Title:~:text=word">named</a><h2 id="Title"></h2>')
        self.assertTrue(self.run_check()["passed"])
        self.assertEqual(self.run_check()["checked_fragments"], 2)

    def test_base_element_controls_relative_resolution(self):
        self.write("nested/index.html", '<base href="/manual/"><a href="topic/#Title">topic</a>')
        self.write("topic/index.html", '<h2 id="Title"></h2>')
        self.assertTrue(self.run_check()["passed"])

    def test_target_symlink_cannot_read_outside_root(self):
        with tempfile.TemporaryDirectory() as other:
            target = Path(other) / "private.html"
            target.write_text('<h2 id="Private"></h2>')
            self.write("index.html", '<a href="alias/private.html#Private">outside</a>')
            (self.root / "alias").symlink_to(other, target_is_directory=True)
            result = self.run_check()
            self.assertFalse(result["passed"])
            self.assertEqual(result["broken"][0]["reason"], "target resolves outside rendered root")

    def test_check_does_not_modify_html(self):
        path = self.write("index.html", '<a href="#Title">valid</a><h2 id="Title"></h2>')
        before = path.read_bytes()
        self.run_check()
        self.assertEqual(path.read_bytes(), before)

    def test_empty_artifact_is_not_a_successful_check(self):
        with self.assertRaisesRegex(ValueError, "no rendered HTML"):
            self.run_check()


if __name__ == "__main__":
    unittest.main()
