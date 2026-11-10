#!/usr/bin/env python3
"""Build an interactive single-file HTML checklist from Markdown tables.

The Markdown source is canonical. Table headers, column order, item numbers, and
cell text are preserved. A browser-side checkbox is added inside the ``項目``
cell of every table that contains both ``項番`` and ``項目`` columns.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence


HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
LIST_RE = re.compile(r"^(\s*)[-*+]\s+(.+?)\s*$")
ORDERED_LIST_RE = re.compile(r"^(\s*)\d+[.)]\s+(.+?)\s*$")
SEPARATOR_CELL_RE = re.compile(r"^:?-{3,}:?$")
LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
ITEM_NUMBER_RE = re.compile(r"^[0-9]+(?:\.[0-9]+)*-[0-9]+$")


class BuildError(ValueError):
    """Raised when the Markdown checklist is structurally invalid."""


@dataclass(frozen=True)
class Table:
    headers: list[str]
    rows: list[list[str]]
    section_path: tuple[str, ...]
    table_index: int


@dataclass(frozen=True)
class BuildResult:
    title: str
    document_id: str
    row_count: int
    requirements: tuple[str, ...]
    html: str


def split_table_row(line: str) -> list[str]:
    """Split a Markdown table row while respecting escapes and code spans."""
    value = line.strip()
    if value.startswith("|"):
        value = value[1:]
    if value.endswith("|") and not value.endswith(r"\|"):
        value = value[:-1]

    cells: list[str] = []
    current: list[str] = []
    escaped = False
    in_code = False

    for char in value:
        if escaped:
            current.append(char)
            escaped = False
            continue
        if char == "\\":
            escaped = True
            current.append(char)
            continue
        if char == "`":
            in_code = not in_code
            current.append(char)
            continue
        if char == "|" and not in_code:
            cells.append("".join(current).strip().replace(r"\|", "|"))
            current = []
            continue
        current.append(char)

    if escaped:
        current.append("\\")
    cells.append("".join(current).strip().replace(r"\|", "|"))
    return cells


def is_separator_row(line: str) -> bool:
    cells = split_table_row(line)
    return bool(cells) and all(SEPARATOR_CELL_RE.fullmatch(cell) for cell in cells)


def looks_like_table(lines: Sequence[str], index: int) -> bool:
    if index + 1 >= len(lines):
        return False
    return lines[index].lstrip().startswith("|") and is_separator_row(lines[index + 1])


def strip_inline_markdown(value: str) -> str:
    value = BR_RE.sub(" ", value)
    value = re.sub(r"`([^`]*)`", r"\1", value)
    value = LINK_RE.sub(r"\1", value)
    value = value.replace("**", "").replace("__", "")
    return re.sub(r"\s+", " ", value).strip()


def render_inline(value: str) -> str:
    """Render the small inline Markdown/HTML subset used by the checklists."""
    output: list[str] = []
    plain: list[str] = []
    i = 0

    def flush_plain() -> None:
        if plain:
            output.append(html.escape("".join(plain), quote=False))
            plain.clear()

    while i < len(value):
        br_match = BR_RE.match(value, i)
        if br_match:
            flush_plain()
            output.append("<br>")
            i = br_match.end()
            continue

        if value.startswith("**", i):
            end = value.find("**", i + 2)
            if end != -1:
                flush_plain()
                output.append(f"<strong>{render_inline(value[i + 2:end])}</strong>")
                i = end + 2
                continue

        if value[i] == "`":
            end = value.find("`", i + 1)
            if end != -1:
                flush_plain()
                output.append(f"<code>{html.escape(value[i + 1:end])}</code>")
                i = end + 1
                continue

        if value[i] == "[":
            match = LINK_RE.match(value, i)
            if match:
                flush_plain()
                label, url = match.groups()
                safe_url = html.escape(url, quote=True)
                output.append(
                    f'<a href="{safe_url}" rel="noopener noreferrer">'
                    f"{html.escape(label)}</a>"
                )
                i = match.end()
                continue

        plain.append(value[i])
        i += 1

    flush_plain()
    return "".join(output)


def slugify(value: str) -> str:
    normalized = strip_inline_markdown(value).lower()
    normalized = re.sub(r"\s+", "-", normalized)
    normalized = re.sub(r"[^0-9a-z\-\u3040-\u30ff\u3400-\u9fff]", "", normalized)
    normalized = re.sub(r"-+", "-", normalized).strip("-")
    return normalized or "section"


def column_class(header: str) -> str:
    mapping = {
        "項番": "col-number",
        "項目": "col-item",
        "区分": "col-requirement",
        "詳細": "col-detail",
    }
    return mapping.get(strip_inline_markdown(header), "")


def stable_row_id(document_id: str, item_number: str) -> str:
    payload = f"{document_id}\0{item_number}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def render_table(
    table: Table,
    document_id: str,
    seen_item_numbers: set[str],
) -> tuple[str, int, set[str]]:
    headers = table.headers
    if not headers or any(not header for header in headers):
        raise BuildError(f"表{table.table_index}: 空のヘッダーがあります。")

    try:
        number_index = headers.index("項番")
        item_index = headers.index("項目")
    except ValueError as exc:
        raise BuildError(
            f"表{table.table_index}: チェック対象の表には「項番」と「項目」が必要です。"
        ) from exc

    requirement_index = headers.index("区分") if "区分" in headers else None
    requirements: set[str] = set()

    parts = [
        '<div class="table-wrap">',
        f'<table class="checklist-table columns-{len(headers)}">',
        "<colgroup>",
    ]
    for header in headers:
        cls = column_class(header)
        class_attr = f' class="{cls}"' if cls else ""
        parts.append(f"<col{class_attr}>")
    parts.extend(["</colgroup>", "<thead><tr>"])
    for header in headers:
        cls = column_class(header)
        class_attr = f' class="{cls}"' if cls else ""
        parts.append(f'<th scope="col"{class_attr}>{render_inline(header)}</th>')
    parts.extend(["</tr></thead>", "<tbody>"])

    for row_index, cells in enumerate(table.rows, start=1):
        if len(cells) != len(headers):
            raise BuildError(
                f"表{table.table_index} 行{row_index}: 列数が一致しません。"
                f" ヘッダー={len(headers)}、行={len(cells)}"
            )

        item_number = strip_inline_markdown(cells[number_index])
        if not item_number:
            raise BuildError(f"表{table.table_index} 行{row_index}: 項番が空です。")
        if not ITEM_NUMBER_RE.fullmatch(item_number):
            raise BuildError(
                f"表{table.table_index} 行{row_index}: 項番の形式が不正です: {item_number}"
            )
        if item_number in seen_item_numbers:
            raise BuildError(f"項番が重複しています: {item_number}")
        seen_item_numbers.add(item_number)

        row_id = stable_row_id(document_id, item_number)
        requirement = (
            strip_inline_markdown(cells[requirement_index])
            if requirement_index is not None
            else "区分なし"
        )
        if requirement_index is not None and requirement:
            requirements.add(requirement)

        searchable = " ".join(strip_inline_markdown(cell) for cell in cells)
        label = strip_inline_markdown(cells[item_index]) or item_number

        parts.append(
            f'<tr data-row-id="{row_id}" '
            f'data-item-number="{html.escape(item_number, quote=True)}" '
            f'data-requirement="{html.escape(requirement, quote=True)}" '
            f'data-search="{html.escape(searchable, quote=True)}">'
        )
        for cell_index, cell in enumerate(cells):
            cls = column_class(headers[cell_index])
            class_attr = f' class="{cls}"' if cls else ""
            if cell_index == item_index:
                parts.append(f'<td class="item-cell {cls}">')
                parts.append(
                    '<label class="check-control" title="確認済みにする">'
                    f'<input class="row-check" type="checkbox" '
                    f'data-row-id="{row_id}" '
                    f'data-item-number="{html.escape(item_number, quote=True)}" '
                    f'aria-label="{html.escape(item_number + " " + label, quote=True)}">'
                    '<span class="check-mark" aria-hidden="true"></span>'
                    f'<span class="cell-content">{render_inline(cell)}</span>'
                    "</label>"
                )
                parts.append("</td>")
            else:
                parts.append(f"<td{class_attr}>{render_inline(cell)}</td>")
        parts.append("</tr>")

    parts.extend(["</tbody>", "</table>", "</div>"])
    return "\n".join(parts), len(table.rows), requirements


def parse_and_render(
    markdown_text: str,
    document_id: str,
) -> tuple[str, str, int, int, tuple[str, ...]]:
    lines = markdown_text.splitlines()
    output: list[str] = []
    heading_stack: list[tuple[int, str]] = []
    slug_counts: dict[str, int] = {}
    title = "チェックリスト"
    table_index = 0
    row_count = 0
    all_requirements: set[str] = set()
    seen_item_numbers: set[str] = set()
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        heading_match = HEADING_RE.match(line)
        if heading_match:
            level = len(heading_match.group(1))
            heading_text = heading_match.group(2).strip()
            if level == 1 and title == "チェックリスト":
                title = strip_inline_markdown(heading_text)

            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, strip_inline_markdown(heading_text)))

            base_slug = slugify(heading_text)
            slug_counts[base_slug] = slug_counts.get(base_slug, 0) + 1
            suffix = "" if slug_counts[base_slug] == 1 else f"-{slug_counts[base_slug]}"
            section_id = f"{base_slug}{suffix}"
            output.append(
                f'<h{level} id="{section_id}">{render_inline(heading_text)}</h{level}>'
            )
            i += 1
            continue

        if looks_like_table(lines, i):
            table_index += 1
            headers = split_table_row(lines[i])
            separator = split_table_row(lines[i + 1])
            if len(headers) != len(separator):
                raise BuildError(
                    f"表{table_index}: ヘッダーと区切り行の列数が一致しません。"
                )
            i += 2
            rows: list[list[str]] = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                if not lines[i].strip():
                    break
                rows.append(split_table_row(lines[i]))
                i += 1

            section_path = tuple(text for _, text in heading_stack)
            table = Table(headers, rows, section_path, table_index)
            rendered, count, requirements = render_table(
                table,
                document_id,
                seen_item_numbers,
            )
            output.append(rendered)
            row_count += count
            all_requirements.update(requirements)
            continue

        if not stripped:
            i += 1
            continue

        list_match = LIST_RE.match(line)
        ordered_match = ORDERED_LIST_RE.match(line)
        if list_match or ordered_match:
            ordered = bool(ordered_match)
            tag = "ol" if ordered else "ul"
            matcher = ORDERED_LIST_RE if ordered else LIST_RE
            items: list[str] = []
            while i < len(lines):
                match = matcher.match(lines[i])
                if not match:
                    break
                items.append(match.group(2))
                i += 1
            output.append(f"<{tag}>")
            output.extend(f"<li>{render_inline(item)}</li>" for item in items)
            output.append(f"</{tag}>")
            continue

        paragraph_lines = [stripped]
        i += 1
        while i < len(lines):
            if not lines[i].strip():
                break
            if HEADING_RE.match(lines[i]) or looks_like_table(lines, i):
                break
            if LIST_RE.match(lines[i]) or ORDERED_LIST_RE.match(lines[i]):
                break
            paragraph_lines.append(lines[i].strip())
            i += 1
        output.append(f"<p>{render_inline(' '.join(paragraph_lines))}</p>")

    if table_index == 0:
        raise BuildError("Markdown内に表が見つかりませんでした。")
    if row_count == 0:
        raise BuildError("チェック項目が見つかりませんでした。")

    requirement_order = ("必須", "推奨", "任意")
    ordered_requirements = tuple(
        item for item in requirement_order if item in all_requirements
    ) + tuple(sorted(all_requirements - set(requirement_order)))

    return title, "\n".join(output), row_count, ordered_requirements


def render_template(template: str, values: dict[str, str]) -> str:
    rendered = template
    for key, value in values.items():
        rendered = rendered.replace("{{" + key + "}}", value)
    remaining = sorted(set(re.findall(r"\{\{([A-Z0-9_]+)\}\}", rendered)))
    if remaining:
        raise BuildError(f"テンプレート変数が未解決です: {', '.join(remaining)}")
    return rendered


def validate_source_file(source: Path, markdown_text: str) -> None:
    """Validate that the selected source is the current table-based checklist."""
    lines = markdown_text.splitlines()
    table_indexes = [
        index for index in range(max(0, len(lines) - 1))
        if looks_like_table(lines, index)
    ]
    if table_indexes:
        return

    preview = " / ".join(
        line.strip() for line in lines if line.strip()
    )[:180]
    raise BuildError(
        f"{source}: Markdown表が見つかりません。"
        " 最新の表形式チェックリストでこのファイルを上書きしてください。"
        " 想定するヘッダーは「| 項番 | 項目 | ... |」です。"
        + (f" 先頭内容: {preview}" if preview else " ファイルは空です。")
    )


def build(
    source: Path,
    template_path: Path,
    output: Path,
) -> BuildResult:
    markdown_text = source.read_text(encoding="utf-8-sig")
    validate_source_file(source, markdown_text)
    template = template_path.read_text(encoding="utf-8")
    document_id = re.sub(r"[^a-zA-Z0-9_-]+", "-", source.stem).strip("-")
    title, content, row_count, requirements = parse_and_render(
        markdown_text,
        document_id,
    )

    requirement_options = "\n".join(
        f'<option value="{html.escape(value, quote=True)}">{html.escape(value)}</option>'
        for value in requirements
    )
    requirement_filter_class = "" if requirements else "is-hidden"

    result_html = render_template(
        template,
        {
            "TITLE": html.escape(title),
            "CONTENT": content,
            "DOCUMENT_ID": html.escape(document_id, quote=True),
            "ROW_COUNT": str(row_count),
            "REQUIREMENT_OPTIONS": requirement_options,
            "REQUIREMENT_FILTER_CLASS": requirement_filter_class,
        },
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(result_html, encoding="utf-8")

    return BuildResult(
        title=title,
        document_id=document_id,
        row_count=row_count,
        requirements=requirements,
        html=result_html,
    )


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="入力するMarkdownファイル")
    parser.add_argument(
        "--template",
        type=Path,
        default=Path("templates/checklist.html"),
        help="HTMLテンプレート",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="生成するHTMLファイル",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="構造エラーを警告ではなく失敗として扱う（現在は常に厳格）",
    )
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = build(args.source, args.template, args.output)
    except (BuildError, OSError) as exc:
        print(f"build error: {exc}", file=sys.stderr)
        return 1

    print(
        f"built {args.output} "
        f"(rows={result.row_count}, "
        f"sha256={result.document_id[:12]}...)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
