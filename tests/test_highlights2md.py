"""Tests for highlights2md color classification and PDF extraction."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import fitz

# Allow importing from project root
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from highlights2md import (  # noqa: E402
    classify_highlight_color,
    extract_highlights,
    process_pdf,
    render_markdown,
)


class TestColorClassification(unittest.TestCase):
    def test_pure_and_tinted_reds(self):
        for rgb in [
            (1.0, 0.0, 0.0),
            (1.0, 0.2, 0.2),  # pink-red
            (0.9, 0.15, 0.1),
            (1.0, 0.35, 0.35),
            (0.85, 0.1, 0.05),  # deep red
        ]:
            with self.subTest(rgb=rgb):
                self.assertEqual(classify_highlight_color(rgb), "red")

    def test_pure_and_tinted_yellows(self):
        for rgb in [
            (1.0, 1.0, 0.0),
            (1.0, 0.9, 0.3),  # light gold
            (1.0, 0.85, 0.0),
            (0.95, 0.88, 0.25),
            (1.0, 0.75, 0.2),  # warm yellow / soft orange-yellow
        ]:
            with self.subTest(rgb=rgb):
                self.assertEqual(classify_highlight_color(rgb), "yellow")

    def test_pure_and_tinted_greens(self):
        for rgb in [
            (0.0, 1.0, 0.0),
            (0.2, 0.8, 0.3),
            (0.1, 0.7, 0.4),  # teal-green
            (0.35, 0.85, 0.45),
            (0.0, 0.65, 0.35),
        ]:
            with self.subTest(rgb=rgb):
                self.assertEqual(classify_highlight_color(rgb), "green")

    def test_other_colors(self):
        for rgb in [
            (0.1, 0.3, 0.9),  # blue
            (0.6, 0.2, 0.9),  # purple
            (0.5, 0.5, 0.5),  # gray
            (0.95, 0.95, 0.95),  # near white
            (0.05, 0.05, 0.05),  # near black
        ]:
            with self.subTest(rgb=rgb):
                self.assertEqual(classify_highlight_color(rgb), "other")

    def test_none_is_other(self):
        self.assertEqual(classify_highlight_color(None), "other")


def _build_fixture_pdf(path: Path) -> None:
    """Create a PDF with non-pure red/yellow/green highlights."""
    doc = fitz.open()
    page = doc.new_page()
    samples = [
        (72, 100, "Alpha red phrase for importance.", "red phrase", (1.0, 0.25, 0.25)),
        (72, 140, "Beta yellow phrase for key points.", "yellow phrase", (1.0, 0.9, 0.35)),
        (72, 180, "Gamma green phrase for definitions.", "green phrase", (0.25, 0.8, 0.35)),
        (72, 220, "Delta blue phrase should be other.", "blue phrase", (0.2, 0.35, 0.95)),
    ]
    for x, y, full, _, _ in samples:
        page.insert_text((x, y), full, fontsize=12)

    for _, _, _, phrase, color in samples:
        for rect in page.search_for(phrase):
            annot = page.add_highlight_annot(rect)
            annot.set_colors(stroke=color)
            annot.set_info(content=f"note:{phrase}")
            annot.update()

    # second page for --pages filtering
    page2 = doc.new_page()
    page2.insert_text((72, 100), "Second page only red here.", fontsize=12)
    for rect in page2.search_for("only red"):
        annot = page2.add_highlight_annot(rect)
        annot.set_colors(stroke=(0.95, 0.15, 0.15))
        annot.update()

    doc.save(path)
    doc.close()


class TestExtraction(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.pdf_path = Path(self.tmp.name) / "sample.pdf"
        _build_fixture_pdf(self.pdf_path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_extract_categories_and_text(self):
        doc = fitz.open(self.pdf_path)
        try:
            items = extract_highlights(doc)
        finally:
            doc.close()

        self.assertEqual(len(items), 5)  # 4 on page1 + 1 on page2
        by_text = {it.text: it for it in items}

        self.assertIn("red phrase", by_text)
        self.assertEqual(by_text["red phrase"].category, "red")
        self.assertEqual(by_text["red phrase"].label, "重点/错误")
        self.assertEqual(by_text["red phrase"].note, "note:red phrase")

        self.assertEqual(by_text["yellow phrase"].category, "yellow")
        self.assertEqual(by_text["yellow phrase"].label, "要点")

        self.assertEqual(by_text["green phrase"].category, "green")
        self.assertEqual(by_text["green phrase"].label, "定义")

        self.assertEqual(by_text["blue phrase"].category, "other")
        self.assertEqual(by_text["only red"].category, "red")
        self.assertEqual(by_text["only red"].page, 2)

    def test_page_filter(self):
        doc = fitz.open(self.pdf_path)
        try:
            items = extract_highlights(doc, page_indices=[1])  # page 2 only
        finally:
            doc.close()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].text, "only red")

    def test_process_and_markdown(self):
        out_dir = Path(self.tmp.name) / "out"
        md_path = process_pdf(
            self.pdf_path,
            out_dir,
            group_by="page",
            write_json=True,
        )
        md = md_path.read_text(encoding="utf-8")
        self.assertIn("重点/错误", md)
        self.assertIn("要点", md)
        self.assertIn("定义", md)
        self.assertIn("red phrase", md)
        self.assertIn("yellow phrase", md)
        self.assertIn("green phrase", md)
        self.assertTrue((out_dir / "sample_highlights.json").exists())

        doc = fitz.open(self.pdf_path)
        try:
            items = extract_highlights(doc)
        finally:
            doc.close()
        grouped = render_markdown(items, source_name="sample.pdf", group_by="color")
        self.assertIn("重点/错误", grouped)
        self.assertIn("p.1", grouped)


if __name__ == "__main__":
    unittest.main()
