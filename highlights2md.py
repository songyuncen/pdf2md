"""
Extract PDF highlight annotations to Markdown, classified by color tendency.

Color mapping (approximate hue, not exact RGB):
  reddish  -> 重点/错误
  yellowish -> 要点
  greenish -> 定义
"""

from __future__ import annotations

import argparse
import colorsys
import json
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal, Sequence

import fitz

Category = Literal["red", "yellow", "green", "other"]

CATEGORY_LABELS: dict[Category, str] = {
    "red": "重点/错误",
    "yellow": "要点",
    "green": "定义",
    "other": "其他",
}

CATEGORY_EMOJI: dict[Category, str] = {
    "red": "🔴",
    "yellow": "🟡",
    "green": "🟢",
    "other": "⬜",
}

# Prototype colors in RGB [0,1] for nearest-class matching (covers non-pure tints).
COLOR_PROTOTYPES: dict[Category, list[tuple[float, float, float]]] = {
    "red": [
        (1.0, 0.0, 0.0),
        (1.0, 0.25, 0.25),
        (0.95, 0.15, 0.15),
        (0.9, 0.2, 0.0),
        (0.85, 0.1, 0.3),
        (1.0, 0.4, 0.4),
    ],
    "yellow": [
        (1.0, 1.0, 0.0),
        (1.0, 0.92, 0.2),
        (1.0, 0.85, 0.0),
        (1.0, 0.9, 0.4),
        (0.95, 0.8, 0.2),
        (1.0, 0.75, 0.15),
    ],
    "green": [
        (0.0, 1.0, 0.0),
        (0.2, 0.85, 0.25),
        (0.0, 0.75, 0.35),
        (0.3, 0.9, 0.3),
        (0.1, 0.7, 0.45),
        (0.4, 0.85, 0.5),
    ],
}

# Max weighted HSV distance to still accept a prototype match.
DEFAULT_MAX_DISTANCE = 0.55
DEFAULT_MIN_SATURATION = 0.12
DEFAULT_MIN_VALUE = 0.12


@dataclass
class HighlightItem:
    page: int
    category: Category
    label: str
    rgb: tuple[float, float, float]
    text: str
    note: str
    rect: tuple[float, float, float, float]


def parse_pages(pages: str, total: int) -> list[int]:
    """Parse page range string like '1-5,10,12-15' into 0-based indices."""
    indices: list[int] = []
    for part in pages.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start_s, end_s = part.split("-", 1)
            start, end = int(start_s), int(end_s)
            indices.extend(range(max(start, 1) - 1, min(end, total)))
        else:
            idx = int(part) - 1
            if 0 <= idx < total:
                indices.append(idx)
    # preserve order, drop duplicates
    seen: set[int] = set()
    ordered: list[int] = []
    for i in indices:
        if i not in seen:
            seen.add(i)
            ordered.append(i)
    return ordered


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def normalize_rgb(color: Sequence[float] | None) -> tuple[float, float, float] | None:
    """Normalize stroke color to RGB floats in [0,1]."""
    if not color:
        return None
    vals = [_clamp01(c) for c in color]
    if len(vals) == 1:
        g = vals[0]
        return (g, g, g)
    if len(vals) == 3:
        return (vals[0], vals[1], vals[2])
    if len(vals) == 4:
        # simple CMYK -> RGB approximation
        c, m, y, k = vals
        r = (1.0 - c) * (1.0 - k)
        g = (1.0 - m) * (1.0 - k)
        b = (1.0 - y) * (1.0 - k)
        return (_clamp01(r), _clamp01(g), _clamp01(b))
    return None


def rgb_to_hsv(rgb: tuple[float, float, float]) -> tuple[float, float, float]:
    """Return (H in degrees [0,360), S, V)."""
    r, g, b = rgb
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    return (h * 360.0, s, v)


def hue_distance(h1: float, h2: float) -> float:
    """Circular distance between two hues in degrees, result in [0, 180]."""
    d = abs(h1 - h2) % 360.0
    return min(d, 360.0 - d)


def rgb_to_hex(rgb: tuple[float, float, float]) -> str:
    r, g, b = (int(round(_clamp01(c) * 255)) for c in rgb)
    return f"#{r:02X}{g:02X}{b:02X}"


def _hue_sector(h: float, rgb: tuple[float, float, float]) -> Category | None:
    """Map hue to reddish/yellowish/greenish sector, or None if outside."""
    if h >= 330 or h < 25:
        return "red"
    if 25 <= h < 42:
        # Orange: warmer (less G) -> red, goldener (more G) -> yellow
        r, g, _b = rgb
        return "red" if g < 0.55 * r + 0.15 else "yellow"
    if 42 <= h < 78:
        return "yellow"
    if 78 <= h < 165:
        return "green"
    return None


def _prototype_distance(
    rgb: tuple[float, float, float],
    proto: tuple[float, float, float],
) -> float:
    h, s, v = rgb_to_hsv(rgb)
    ph, ps, pv = rgb_to_hsv(proto)
    dh = hue_distance(h, ph) / 180.0
    ds = abs(s - ps)
    dv = abs(v - pv)
    return 0.7 * dh + 0.2 * ds + 0.1 * dv


def classify_highlight_color(
    rgb: tuple[float, float, float] | None,
    *,
    min_saturation: float = DEFAULT_MIN_SATURATION,
    min_value: float = DEFAULT_MIN_VALUE,
    max_distance: float = DEFAULT_MAX_DISTANCE,
) -> Category:
    """
    Classify highlight color by tendency (reddish / yellowish / greenish).

    Sector-first on hue so blue/purple are never forced into R/Y/G, then refine
    with prototype distance inside the sector (handles pink, light yellow, etc.).
    """
    if rgb is None:
        return "other"

    h, s, v = rgb_to_hsv(rgb)
    if s < min_saturation or v < min_value:
        return "other"

    sector = _hue_sector(h, rgb)
    if sector is None:
        return "other"

    # Within R/Y/G sectors, confirm closeness to at least one prototype of that class
    # (or an adjacent class for soft orange boundaries).
    candidates: list[Category] = [sector]
    if sector == "red":
        candidates.append("yellow")
    elif sector == "yellow":
        candidates.extend(["red", "green"])
    elif sector == "green":
        candidates.append("yellow")

    best_cat: Category = sector
    best_dist = float("inf")
    for cat in candidates:
        for proto in COLOR_PROTOTYPES[cat]:
            dist = _prototype_distance(rgb, proto)
            if dist < best_dist:
                best_dist = dist
                best_cat = cat

    if best_dist > max_distance:
        # Still inside a valid hue sector — trust sector for typical highlighter tints
        return sector
    return best_cat


def extract_annot_text(page: fitz.Page, annot: fitz.Annot) -> str:
    """Extract text covered by a highlight using word/quad intersection."""
    words = page.get_text("words")  # x0,y0,x1,y1,word,block,line,word_no
    if not words:
        return ""

    verts = annot.vertices
    quads: list[fitz.Quad] = []
    if verts and len(verts) >= 4:
        for i in range(0, len(verts), 4):
            pts = verts[i : i + 4]
            if len(pts) < 4:
                break
            quads.append(fitz.Quad(pts))

    selected: list[tuple] = []
    if quads:
        for w in words:
            wr = fitz.Rect(w[:4])
            center = fitz.Point((w[0] + w[2]) / 2, (w[1] + w[3]) / 2)
            for q in quads:
                qr = q.rect
                if not wr.intersects(qr):
                    continue
                inter = wr & qr
                if qr.contains(center) or inter.get_area() >= 0.4 * wr.get_area():
                    selected.append(w)
                    break
    else:
        rect = annot.rect
        for w in words:
            wr = fitz.Rect(w[:4])
            if wr.intersects(rect):
                inter = wr & rect
                if inter.get_area() >= 0.4 * wr.get_area():
                    selected.append(w)

    if not selected:
        # fallback: clip rect (may include edge characters)
        raw = page.get_text("text", clip=annot.rect) or ""
        return " ".join(raw.split())

    selected.sort(key=lambda w: (w[5], w[6], w[7]))
    # Join words; keep CJK without forcing spaces between CJK runs.
    parts: list[str] = []
    for i, w in enumerate(selected):
        token = w[4]
        if i == 0:
            parts.append(token)
            continue
        prev = parts[-1]
        # If either side is mostly CJK, avoid extra space when already adjacent in line.
        if _is_cjk(prev[-1:]) and _is_cjk(token[:1]):
            parts.append(token)
        else:
            parts.append(" " + token)
    return "".join(parts).strip()


def _is_cjk(ch: str) -> bool:
    if not ch:
        return False
    code = ord(ch)
    return (
        0x4E00 <= code <= 0x9FFF
        or 0x3400 <= code <= 0x4DBF
        or 0xF900 <= code <= 0xFAFF
        or 0x3000 <= code <= 0x303F
        or 0xFF00 <= code <= 0xFFEF
    )


def extract_highlights(
    doc: fitz.Document,
    *,
    page_indices: Sequence[int] | None = None,
    min_saturation: float = DEFAULT_MIN_SATURATION,
    min_value: float = DEFAULT_MIN_VALUE,
    include_notes: bool = True,
) -> list[HighlightItem]:
    """Scan document pages and collect highlight annotations."""
    if page_indices is None:
        indices = list(range(doc.page_count))
    else:
        indices = list(page_indices)

    items: list[HighlightItem] = []
    for idx in indices:
        page = doc[idx]
        for annot in page.annots(types=[fitz.PDF_ANNOT_HIGHLIGHT]) or []:
            stroke = None
            colors = annot.colors or {}
            stroke = normalize_rgb(colors.get("stroke"))
            category = classify_highlight_color(
                stroke,
                min_saturation=min_saturation,
                min_value=min_value,
            )
            text = extract_annot_text(page, annot)
            note = ""
            if include_notes:
                info = annot.info or {}
                note = (info.get("content") or "").strip()
            rgb = stroke or (0.5, 0.5, 0.5)
            rect = annot.rect
            items.append(
                HighlightItem(
                    page=idx + 1,
                    category=category,
                    label=CATEGORY_LABELS[category],
                    rgb=(round(rgb[0], 4), round(rgb[1], 4), round(rgb[2], 4)),
                    text=text,
                    note=note,
                    rect=(rect.x0, rect.y0, rect.x1, rect.y1),
                )
            )
    return items


def _format_item_line(
    item: HighlightItem,
    *,
    show_color: bool = False,
    page_prefix: bool = False,
) -> str:
    emoji = CATEGORY_EMOJI[item.category]
    label = item.label
    if item.category == "other":
        label = f"其他 {rgb_to_hex(item.rgb)}"
    elif show_color:
        label = f"{item.label} {rgb_to_hex(item.rgb)}"
    if page_prefix:
        label = f"p.{item.page} · {label}"

    body = item.text if item.text else "_(无文本层或未能提取文字)_"
    line = f"- {emoji} **[{label}]** {body}"
    if item.note:
        line += f"\n  - 备注：{item.note}"
    return line


def render_markdown(
    items: Sequence[HighlightItem],
    *,
    source_name: str,
    group_by: Literal["page", "color"] = "page",
    show_color: bool = False,
) -> str:
    counts: dict[Category, int] = defaultdict(int)
    for it in items:
        counts[it.category] += 1

    lines: list[str] = [
        f"# Highlights: {source_name}",
        "",
        (
            f"> 共 {len(items)} 条高亮 · "
            f"红 {counts['red']} · 黄 {counts['yellow']} · "
            f"绿 {counts['green']} · 其他 {counts['other']}"
        ),
        "",
    ]

    if not items:
        lines.append("_未找到 Highlight 标注。_")
        lines.append("")
        lines.append(
            "说明：仅支持 PDF 中的 Highlight 注释（阅读器勾画）。"
            "若高亮已压成图片/路径而无标注对象，则无法提取。"
        )
        lines.append("")
        return "\n".join(lines)

    if group_by == "page":
        by_page: dict[int, list[HighlightItem]] = defaultdict(list)
        for it in items:
            by_page[it.page].append(it)
        for page_no in sorted(by_page):
            lines.append(f"## 第 {page_no} 页")
            lines.append("")
            for it in by_page[page_no]:
                lines.append(_format_item_line(it, show_color=show_color))
            lines.append("")
    else:
        order: list[Category] = ["red", "yellow", "green", "other"]
        by_cat: dict[Category, list[HighlightItem]] = defaultdict(list)
        for it in items:
            by_cat[it.category].append(it)
        for cat in order:
            group = by_cat.get(cat) or []
            if not group:
                continue
            lines.append(f"## {CATEGORY_EMOJI[cat]} {CATEGORY_LABELS[cat]}（{len(group)}）")
            lines.append("")
            for it in group:
                lines.append(
                    _format_item_line(it, show_color=show_color, page_prefix=True)
                )
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def render_json(items: Sequence[HighlightItem], *, source_name: str) -> str:
    payload = {
        "source": source_name,
        "count": len(items),
        "highlights": [
            {
                **asdict(it),
                "rgb_hex": rgb_to_hex(it.rgb),
            }
            for it in items
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def process_pdf(
    pdf_path: Path,
    output_dir: Path,
    *,
    pages: str | None = None,
    group_by: Literal["page", "color"] = "page",
    write_json: bool = False,
    include_notes: bool = True,
    show_color: bool = False,
    min_saturation: float = DEFAULT_MIN_SATURATION,
) -> Path:
    doc = fitz.open(pdf_path)
    try:
        page_indices = parse_pages(pages, doc.page_count) if pages else None
        if pages and not page_indices:
            raise ValueError(f"No valid pages in range '{pages}' (total: {doc.page_count})")

        items = extract_highlights(
            doc,
            page_indices=page_indices,
            min_saturation=min_saturation,
            include_notes=include_notes,
        )
    finally:
        doc.close()

    output_dir.mkdir(parents=True, exist_ok=True)
    stem = pdf_path.stem
    md_path = output_dir / f"{stem}_highlights.md"
    md = render_markdown(
        items,
        source_name=pdf_path.name,
        group_by=group_by,
        show_color=show_color,
    )
    md_path.write_text(md, encoding="utf-8")

    if write_json:
        json_path = output_dir / f"{stem}_highlights.json"
        json_path.write_text(
            render_json(items, source_name=pdf_path.name),
            encoding="utf-8",
        )

    print(f"{pdf_path.name}: {len(items)} highlights -> {md_path}")
    return md_path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Extract PDF highlight annotations to Markdown (by color tendency)."
    )
    parser.add_argument("pdf", nargs="+", help="Path(s) to input PDF file(s)")
    parser.add_argument(
        "-o",
        "--output",
        default="output",
        help="Output directory (default: output)",
    )
    parser.add_argument(
        "--pages",
        default=None,
        help="Page range, e.g. '1-20' or '1-5,10-15'",
    )
    parser.add_argument(
        "--group-by",
        choices=["page", "color"],
        default="page",
        help="Group markdown by page (default) or color",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Also write a JSON sidecar",
    )
    parser.add_argument(
        "--no-notes",
        action="store_true",
        help="Do not include annotation popup notes",
    )
    parser.add_argument(
        "--show-color",
        action="store_true",
        help="Include raw RGB hex next to labels (for calibration)",
    )
    parser.add_argument(
        "--min-saturation",
        type=float,
        default=DEFAULT_MIN_SATURATION,
        help=f"Min HSV saturation to classify as colored (default: {DEFAULT_MIN_SATURATION})",
    )
    args = parser.parse_args(argv)

    out = Path(args.output)
    any_ok = False
    for pdf in args.pdf:
        path = Path(pdf)
        if not path.exists():
            print(f"Error: file not found: {pdf}", file=sys.stderr)
            continue
        try:
            process_pdf(
                path,
                out,
                pages=args.pages,
                group_by=args.group_by,
                write_json=args.json,
                include_notes=not args.no_notes,
                show_color=args.show_color,
                min_saturation=args.min_saturation,
            )
            any_ok = True
        except Exception as exc:
            print(f"Error processing {pdf}: {exc}", file=sys.stderr)

    return 0 if any_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
