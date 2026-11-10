from __future__ import annotations

import html
import importlib.util
import re
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_checklist.py"
SPEC = importlib.util.spec_from_file_location("build_checklist", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class ChecklistBuildTests(unittest.TestCase):
    def setUp(self) -> None:
        self.customer = ROOT / "checklist_for_customer.md"
        self.reporter = ROOT / "checklist_for_reporter.md"
        self.template = ROOT / "templates" / "checklist.html"

    def table_headers(self, source: Path) -> list[list[str]]:
        lines = source.read_text(encoding="utf-8").splitlines()
        return [
            MODULE.split_table_row(lines[index])
            for index in range(len(lines) - 1)
            if MODULE.looks_like_table(lines, index)
        ]

    def source_rows(self, source: Path) -> list[list[str]]:
        lines = source.read_text(encoding="utf-8").splitlines()
        rows: list[list[str]] = []
        for index in range(len(lines) - 1):
            if not MODULE.looks_like_table(lines, index):
                continue
            row = index + 2
            while row < len(lines) and lines[row].lstrip().startswith("|"):
                rows.append(MODULE.split_table_row(lines[row]))
                row += 1
        return rows

    def test_all_tables_have_item_number_and_item_columns(self) -> None:
        for source in (self.customer, self.reporter):
            headers = self.table_headers(source)
            self.assertGreater(
                len(headers),
                0,
                f"{source} にMarkdown表がありません。最新の表形式ファイルで上書きしてください。",
            )
            for header in headers:
                self.assertIn("項番", header)
                self.assertIn("項目", header)

    def test_builds_both_current_checklists(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            directory_path = Path(directory)
            customer_result = MODULE.build(
                self.customer,
                self.template,
                directory_path / "customer.html",
            )
            reporter_result = MODULE.build(
                self.reporter,
                self.template,
                directory_path / "reporter.html",
            )
            self.assertEqual(customer_result.row_count, len(self.source_rows(self.customer)))
            self.assertEqual(reporter_result.row_count, len(self.source_rows(self.reporter)))
            self.assertEqual(customer_result.requirements, ())
            self.assertIn("必須", reporter_result.requirements)

    def test_checkbox_is_inserted_in_item_cell_not_number_cell(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "customer.html"
            MODULE.build(self.customer, self.template, output)
            generated = output.read_text(encoding="utf-8")
            self.assertRegex(
                generated,
                r'<td class="col-number">1-1</td>\s*<td class="item-cell col-item">\s*<label class="check-control"',
            )

    def test_customer_hides_requirement_filter_and_reporter_populates_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            directory_path = Path(directory)
            customer_output = directory_path / "customer.html"
            reporter_output = directory_path / "reporter.html"
            MODULE.build(self.customer, self.template, customer_output)
            MODULE.build(self.reporter, self.template, reporter_output)
            customer_html = customer_output.read_text(encoding="utf-8")
            reporter_html = reporter_output.read_text(encoding="utf-8")
            self.assertIn('<label class="control is-hidden">', customer_html)
            self.assertIn('<option value="必須">必須</option>', reporter_html)
            self.assertIn('<option value="推奨">推奨</option>', reporter_html)
            self.assertIn('<option value="任意">任意</option>', reporter_html)

    def test_all_source_items_are_present_in_generated_html(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            for source in (self.customer, self.reporter):
                output = Path(directory) / f"{source.stem}.html"
                MODULE.build(source, self.template, output)
                generated = output.read_text(encoding="utf-8")
                visible_text = re.sub(r"<[^>]+>", " ", generated)
                visible_text = html.unescape(visible_text)
                for row in self.source_rows(source):
                    headers = self.table_headers(source)
                    # Every current table places the item in the second column.
                    item_plain = MODULE.strip_inline_markdown(row[1])
                    self.assertIn(item_plain, visible_text)

    def test_mixed_two_and_three_column_tables_use_colgroup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "customer.html"
            MODULE.build(self.customer, self.template, output)
            generated = output.read_text(encoding="utf-8")
            self.assertIn('<table class="checklist-table columns-2">', generated)
            self.assertIn('<table class="checklist-table columns-3">', generated)
            self.assertIn('<col class="col-number">', generated)
            self.assertIn('<col class="col-item">', generated)
            self.assertIn('<col class="col-detail">', generated)
            self.assertIn('thead th.col-item', generated)

    def test_literal_br_tags_are_rendered_as_line_breaks(self) -> None:
        markdown = (
            "# Test\n\n"
            "| 項番 | 項目 | 詳細 |\n"
            "| --- | --- | --- |\n"
            "| 1-1 | A | first<br>- second |\n"
        )
        _, rendered, row_count, _ = MODULE.parse_and_render(markdown, "test")
        self.assertEqual(row_count, 1)
        self.assertIn("first<br>- second", rendered)
        self.assertNotIn("&lt;br", rendered)

    def test_item_number_provides_stable_row_id(self) -> None:
        first = MODULE.stable_row_id("document", "3.2-1")
        second = MODULE.stable_row_id("document", "3.2-1")
        other = MODULE.stable_row_id("document", "3.2-2")
        self.assertEqual(first, second)
        self.assertNotEqual(first, other)

    def test_duplicate_item_number_fails(self) -> None:
        broken = (
            "# Test\n\n"
            "| 項番 | 項目 |\n"
            "| --- | --- |\n"
            "| 1-1 | A |\n"
            "| 1-1 | B |\n"
        )
        with self.assertRaises(MODULE.BuildError):
            MODULE.parse_and_render(broken, "test")

    def test_invalid_column_count_fails(self) -> None:
        broken = (
            "# Test\n\n"
            "| 項番 | 項目 | 詳細 |\n"
            "| --- | --- | --- |\n"
            "| 1-1 | A |\n"
        )
        with self.assertRaises(MODULE.BuildError):
            MODULE.parse_and_render(broken, "test")


if __name__ == "__main__":
    unittest.main()
