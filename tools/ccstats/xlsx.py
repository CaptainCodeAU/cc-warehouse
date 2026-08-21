"""A minimal, dependency-free .xlsx writer.

An xlsx file is a zip of XML parts, so `zipfile` plus careful string building is
enough. This exists because the project is stdlib-only and pulling in openpyxl
for one scratch deliverable is not worth the dependency.

Supports what this dataset needs and nothing more: multiple sheets, a bold
frozen header row, autofilter, per-column number formats, and sane column
widths. Strings are written inline, which avoids a shared-string table.
"""

# The OOXML namespace URIs below are fixed by the spec and run past 100 chars.
# Splitting a URI across lines is both less readable and easy to corrupt, so the
# line-length rule is waived for this file only.
# ruff: noqa: E501

from __future__ import annotations

import zipfile
from collections.abc import Sequence
from datetime import UTC, datetime

# Number format ids. 0 is General; 164+ is the custom range.
FMT_GENERAL = 0
FMT_INT = 1
FMT_DEC2 = 2
FMT_MONEY = 3
FMT_PCT = 4

_STYLE_FOR_FMT = {FMT_GENERAL: 0, FMT_INT: 2, FMT_DEC2: 3, FMT_MONEY: 4, FMT_PCT: 5}
_HEADER_STYLE = 1


def col_ref(index: int) -> str:
    """1 -> A, 26 -> Z, 27 -> AA."""
    out = ""
    while index > 0:
        index, rem = divmod(index - 1, 26)
        out = chr(65 + rem) + out
    return out


def esc(value: str) -> str:
    """XML-escape, and drop control characters Excel refuses to open."""
    out = (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
    return "".join(ch for ch in out if ch >= " " or ch in "\t\n")


class Sheet:
    """One tab: a name, a header row, typed rows, and a short description."""

    def __init__(
        self,
        name: str,
        headers: Sequence[str],
        rows: Sequence[Sequence[object]],
        *,
        formats: Sequence[int] | None = None,
        widths: Sequence[int] | None = None,
        description: str = "",
        freeze_header: bool = True,
        autofilter: bool = True,
    ) -> None:
        # Excel caps sheet names at 31 chars and forbids : \ / ? * [ ]
        clean = "".join("-" if ch in ':\\/?*[]' else ch for ch in name)[:31]
        self.name = clean
        self.headers = list(headers)
        self.rows = rows
        self.formats = list(formats) if formats else [FMT_GENERAL] * len(self.headers)
        self.widths = list(widths) if widths else _auto_widths(self.headers, rows)
        self.description = description
        self.freeze_header = freeze_header
        self.autofilter = autofilter


def _auto_widths(headers: Sequence[str], rows: Sequence[Sequence[object]]) -> list[int]:
    """Width from the header plus the first 200 rows. Clamped so one long
    string cannot push a column off the screen."""
    widths = [len(str(h)) + 3 for h in headers]
    for row in list(rows)[:200]:
        for i, cell in enumerate(row):
            if i >= len(widths):
                break
            widths[i] = max(widths[i], min(len(str(cell)) + 2, 60))
    return [max(9, min(w, 60)) for w in widths]


def _cell(ref: str, value: object, style: int) -> str:
    if value is None or value == "":
        return f'<c r="{ref}" s="{style}"/>'
    if isinstance(value, bool):
        return f'<c r="{ref}" s="{style}"><v>{1 if value else 0}</v></c>'
    if isinstance(value, (int, float)):
        return f'<c r="{ref}" s="{style}"><v>{value!r}</v></c>'
    return f'<c r="{ref}" s="{style}" t="inlineStr"><is><t>{esc(str(value))}</t></is></c>'


def _sheet_xml(sheet: Sheet) -> str:
    ncols = len(sheet.headers)
    nrows = len(sheet.rows) + 1
    last = col_ref(ncols) if ncols else "A"

    parts = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
        f'<dimension ref="A1:{last}{max(nrows, 1)}"/>',
        "<sheetViews><sheetView workbookViewId=\"0\">",
    ]
    if sheet.freeze_header:
        parts.append(
            '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
            '<selection pane="bottomLeft" activeCell="A2" sqref="A2"/>'
        )
    parts.append('</sheetView></sheetViews><sheetFormatPr defaultRowHeight="15"/>')

    if ncols:
        parts.append("<cols>")
        for i, width in enumerate(sheet.widths, start=1):
            parts.append(f'<col min="{i}" max="{i}" width="{width}" customWidth="1"/>')
        parts.append("</cols>")

    parts.append("<sheetData>")
    header_cells = "".join(
        _cell(f"{col_ref(i)}1", h, _HEADER_STYLE) for i, h in enumerate(sheet.headers, start=1)
    )
    parts.append(f'<row r="1" s="{_HEADER_STYLE}" customFormat="1">{header_cells}</row>')

    styles = [_STYLE_FOR_FMT.get(f, 0) for f in sheet.formats]
    for rindex, row in enumerate(sheet.rows, start=2):
        cells = "".join(
            _cell(f"{col_ref(cindex)}{rindex}", value, styles[cindex - 1] if cindex - 1 < len(styles) else 0)
            for cindex, value in enumerate(row, start=1)
        )
        parts.append(f'<row r="{rindex}">{cells}</row>')
    parts.append("</sheetData>")

    if sheet.autofilter and ncols and sheet.rows:
        parts.append(f'<autoFilter ref="A1:{last}{nrows}"/>')
    parts.append("</worksheet>")
    return "".join(parts)


_STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<numFmts count="4">
<numFmt numFmtId="164" formatCode="#,##0"/>
<numFmt numFmtId="165" formatCode="#,##0.00"/>
<numFmt numFmtId="166" formatCode="&quot;$&quot;#,##0.00"/>
<numFmt numFmtId="167" formatCode="0.0%"/>
</numFmts>
<fonts count="2">
<font><sz val="11"/><color theme="1"/><name val="Calibri"/><family val="2"/></font>
<font><b/><sz val="11"/><color theme="1"/><name val="Calibri"/><family val="2"/></font>
</fonts>
<fills count="3">
<fill><patternFill patternType="none"/></fill>
<fill><patternFill patternType="gray125"/></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FFE8E8E8"/><bgColor indexed="64"/></patternFill></fill>
</fills>
<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="6">
<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/>
<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
<xf numFmtId="165" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
<xf numFmtId="166" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
<xf numFmtId="167" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
</cellXfs>
<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>"""


def write_workbook(path, sheets: Sequence[Sheet], *, title: str = "", creator: str = "ccstats") -> None:
    """Write every sheet into one .xlsx at `path`."""
    n = len(sheets)

    types = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">',
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>',
        '<Default Extension="xml" ContentType="application/xml"/>',
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>',
        '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>',
    ]
    for i in range(1, n + 1):
        types.append(
            f'<Override PartName="/xl/worksheets/sheet{i}.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        )
    types.append("</Types>")

    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
        "</Relationships>"
    )

    wb_sheets = "".join(
        f'<sheet name="{esc(s.name)}" sheetId="{i}" r:id="rId{i}"/>'
        for i, s in enumerate(sheets, start=1)
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f"<sheets>{wb_sheets}</sheets></workbook>"
    )

    wb_rels_items = "".join(
        f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>'
        for i in range(1, n + 1)
    )
    wb_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f'{wb_rels_items}'
        f'<Relationship Id="rId{n + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
        "</Relationships>"
    )

    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    core = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        f"<dc:title>{esc(title)}</dc:title><dc:creator>{esc(creator)}</dc:creator>"
        f'<dcterms:created xsi:type="dcterms:W3CDTF">{stamp}</dcterms:created>'
        "</cp:coreProperties>"
    )

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", "".join(types))
        zf.writestr("_rels/.rels", rels)
        zf.writestr("docProps/core.xml", core)
        zf.writestr("xl/workbook.xml", workbook)
        zf.writestr("xl/_rels/workbook.xml.rels", wb_rels)
        zf.writestr("xl/styles.xml", _STYLES)
        for i, sheet in enumerate(sheets, start=1):
            zf.writestr(f"xl/worksheets/sheet{i}.xml", _sheet_xml(sheet))
