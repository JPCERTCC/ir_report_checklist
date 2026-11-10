from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location("build_site", SCRIPTS / "build_site.py")
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class SiteBuildTests(unittest.TestCase):
    def test_build_site_creates_both_checklists_landing_and_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "dist"
            customer, reporter = MODULE.build_site(
                ROOT / "checklist_for_customer.md",
                ROOT / "checklist_for_reporter.md",
                ROOT / "templates" / "checklist.html",
                ROOT / "templates" / "landing.html",
                output,
            )
            self.assertGreater(customer.row_count, 0)
            self.assertGreater(reporter.row_count, 0)
            self.assertTrue((output / "index.html").exists())
            self.assertTrue((output / "checklist_for_customer.html").exists())
            self.assertTrue((output / "checklist_for_reporter.html").exists())
            self.assertTrue((output / "markdown" / "checklist_for_customer.md").exists())
            self.assertTrue((output / "markdown" / "checklist_for_reporter.md").exists())

            landing = (output / "index.html").read_text(encoding="utf-8")
            self.assertIn("./checklist_for_customer.html", landing)
            self.assertIn("./checklist_for_reporter.html", landing)
            self.assertNotIn("{{", landing)

    def test_optional_pdf_is_copied_and_linked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "dist"
            pdf = root / "sample.pdf"
            pdf.write_bytes(b"%PDF-1.4\n")
            MODULE.build_site(
                ROOT / "checklist_for_customer.md",
                ROOT / "checklist_for_reporter.md",
                ROOT / "templates" / "checklist.html",
                ROOT / "templates" / "landing.html",
                output,
                pdf,
            )
            self.assertTrue(
                (output / "pdf" / "incident_forensic_report_template_ja.pdf").exists()
            )
            landing = (output / "index.html").read_text(encoding="utf-8")
            self.assertIn("./pdf/incident_forensic_report_template_ja.pdf", landing)


if __name__ == "__main__":
    unittest.main()
