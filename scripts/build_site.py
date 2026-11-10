#!/usr/bin/env python3
"""Build both interactive checklists and the GitHub Pages landing page."""

from __future__ import annotations

import argparse
import html
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from build_checklist import BuildError, BuildResult, build, render_template


def pdf_card(pdf_output: Path | None) -> str:
    if pdf_output is None:
        return ""
    return """
      <article class="card">
        <span class="tag">ユーザーおよびレポーター向け</span>
        <h2>インシデント調査報告書サンプル</h2>
        <p>チェックリストの基準を、実際の報告書構成と記載例に落とし込んだサンプルです。</p>
        <a class="button secondary" href="./pdf/incident_forensic_report_template_ja.pdf">PDFを開く</a>
      </article>
""".strip()


def build_site(
    customer_source: Path,
    reporter_source: Path,
    checklist_template: Path,
    landing_template: Path,
    output_dir: Path,
    pdf_source: Path | None = None,
) -> tuple[BuildResult, BuildResult]:
    output_dir.mkdir(parents=True, exist_ok=True)

    customer_output = output_dir / "checklist_for_customer.html"
    reporter_output = output_dir / "checklist_for_reporter.html"

    customer_result = build(customer_source, checklist_template, customer_output)
    reporter_result = build(reporter_source, checklist_template, reporter_output)

    markdown_dir = output_dir / "markdown"
    markdown_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(customer_source, markdown_dir / "checklist_for_customer.md")
    shutil.copy2(reporter_source, markdown_dir / "checklist_for_reporter.md")

    copied_pdf: Path | None = None
    if pdf_source is not None and pdf_source.exists():
        pdf_dir = output_dir / "pdf"
        pdf_dir.mkdir(parents=True, exist_ok=True)
        copied_pdf = pdf_dir / "incident_forensic_report_template_ja.pdf"
        shutil.copy2(pdf_source, copied_pdf)

    template = landing_template.read_text(encoding="utf-8")
    landing = render_template(
        template,
        {
            "CUSTOMER_TITLE": html.escape(customer_result.title),
            "REPORTER_TITLE": html.escape(reporter_result.title),
            "PDF_CARD": pdf_card(copied_pdf),
        },
    )
    (output_dir / "index.html").write_text(landing, encoding="utf-8")
    return customer_result, reporter_result


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--customer",
        type=Path,
        default=Path("checklist_for_customer.md"),
        help="ユーザー向けMarkdown",
    )
    parser.add_argument(
        "--reporter",
        type=Path,
        default=Path("checklist_for_reporter.md"),
        help="レポーター向けMarkdown",
    )
    parser.add_argument(
        "--checklist-template",
        type=Path,
        default=Path("templates/checklist.html"),
        help="チェックリストHTMLテンプレート",
    )
    parser.add_argument(
        "--landing-template",
        type=Path,
        default=Path("templates/landing.html"),
        help="トップページHTMLテンプレート",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("dist"),
        help="出力ディレクトリ",
    )
    parser.add_argument(
        "--pdf",
        type=Path,
        default=Path("pdf/incident_forensic_report_template_ja.pdf"),
        help="存在する場合に公開へ含める報告書サンプルPDF",
    )
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    pdf = args.pdf if args.pdf.exists() else None
    try:
        customer, reporter = build_site(
            args.customer,
            args.reporter,
            args.checklist_template,
            args.landing_template,
            args.output_dir,
            pdf,
        )
    except (BuildError, OSError) as exc:
        print(f"build error: {exc}", file=sys.stderr)
        return 1

    print(
        "built site "
        f"(customer={customer.row_count} rows, reporter={reporter.row_count} rows)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
