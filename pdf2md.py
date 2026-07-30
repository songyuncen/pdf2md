import argparse
import os
import sys
import tempfile
from pathlib import Path

import fitz
from mineru import MinerU


def extract_pages(pdf_path: str, pages: str) -> str:
    """Extract specified pages into a temp PDF, return its path."""
    doc = fitz.open(pdf_path)
    total = len(doc)

    indices = []
    for part in pages.split(","):
        part = part.strip()
        if "-" in part:
            start, end = part.split("-", 1)
            start, end = int(start), int(end)
            indices.extend(range(max(start, 1) - 1, min(end, total)))
        else:
            idx = int(part) - 1
            if 0 <= idx < total:
                indices.append(idx)

    if not indices:
        doc.close()
        raise ValueError(f"No valid pages in range '{pages}' (total: {total})")

    new_doc = fitz.open()
    new_doc.insert_pdf(doc, from_page=indices[0], to_page=indices[-1])
    doc.close()

    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    tmp.close()
    new_doc.save(tmp.name)
    new_doc.close()
    print(f"Extracted {len(indices)} pages locally -> {tmp.name}")
    return tmp.name


def convert_pdf(
    pdf_path: str,
    output_dir: str,
    token: str,
    model: str = "vlm",
    language: str = "ch",
    pages: str | None = None,
):
    upload_path = pdf_path
    tmp_file = None

    if pages:
        tmp_file = extract_pages(pdf_path, pages)
        upload_path = tmp_file

    try:
        with MinerU(token) as client:
            print(f"Extracting: {pdf_path} (model={model})")
            result = client.extract(
                upload_path,
                model=model,
                ocr=True,
                formula=True,
                table=True,
                language=language,
                timeout=600,
            )

            if result.state != "done":
                print(f"Failed: state={result.state}")
                sys.exit(1)

            out = Path(output_dir)
            out.mkdir(parents=True, exist_ok=True)
            result.save_all(str(out))
            print(f"Saved to: {out / Path(pdf_path).stem}")
    finally:
        if tmp_file:
            os.unlink(tmp_file)


def main():
    parser = argparse.ArgumentParser(description="Convert PDF to Markdown using MinerU API")
    parser.add_argument("pdf", nargs="+", help="Path(s) to input PDF file(s)")
    parser.add_argument("-o", "--output", default="output", help="Output directory (default: output)")
    parser.add_argument("--model", default="vlm", choices=["vlm", "pipeline"], help="Model (default: vlm)")
    parser.add_argument("--language", default="ch", help="Language (default: ch)")
    parser.add_argument("--pages", default=None, help="Page range, e.g. '1-20' or '1-5,10-15'")
    parser.add_argument("--token", default=None, help="API token (or set MINERU_TOKEN env)")
    args = parser.parse_args()

    token = args.token or os.environ.get("MINERU_TOKEN")
    if not token:
        print("Error: provide --token or set MINERU_TOKEN environment variable.")
        print("Get your token at: https://mineru.net/apiManage/token")
        sys.exit(1)

    for pdf in args.pdf:
        if not Path(pdf).exists():
            print(f"Error: file not found: {pdf}")
            continue
        convert_pdf(pdf, args.output, token, model=args.model, language=args.language, pages=args.pages)


if __name__ == "__main__":
    main()
