# pdf2md

Convert PDF to Markdown using [MinerU](https://mineru.net) cloud API. Supports VLM high-accuracy parsing with OCR, formula (LaTeX), and table (HTML) recognition.

## Features

- High-accuracy document parsing via MinerU VLM engine
- OCR, formula, and table recognition enabled by default
- Local page extraction before upload (saves bandwidth for large files)
- Batch conversion support
- Single-file `.exe` build available (no Python required)

## Requirements

- Python 3.12+
- A MinerU API token (free tier available at https://mineru.net/apiManage/token)

## Install

```bash
uv sync
```

## Usage

```bash
# Set your token
export MINERU_TOKEN="your-token"

# Convert a single PDF
uv run pdf2md.py paper.pdf -o output

# Batch convert
uv run pdf2md.py *.pdf -o output

# Specific pages only (extracted locally before upload)
uv run pdf2md.py paper.pdf --pages 1-20

# Non-contiguous pages
uv run pdf2md.py paper.pdf --pages "1-5,10-15"

# Use pipeline model instead of VLM
uv run pdf2md.py paper.pdf --model pipeline
```

## Options

| Flag | Default | Description |
|------|---------|-------------|
| `-o, --output` | `output` | Output directory |
| `--model` | `vlm` | Model: `vlm` (high accuracy) or `pipeline` (fast) |
| `--language` | `ch` | Document language |
| `--pages` | all | Page range, e.g. `1-20` or `1-5,10-15` |
| `--token` | `$MINERU_TOKEN` | API token |

## Build exe

```bash
uv run pyinstaller --onefile --name pdf2md pdf2md.py
# Output: dist/pdf2md.exe
```

## License

MIT
