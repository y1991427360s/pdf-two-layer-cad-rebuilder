# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

- Install deps: `pip install -r requirements.txt` (or run `install_dependencies.bat`).
- Launch GUI: `python main.py` (or `run_gui.bat`). `main.py` just calls `cad_pdf_rebuilder.app.main`.
- CLI / scripted use: see `run_cli_example.py` — call `rebuild_many(pdfs, out_dir, RebuildOptions(...), print)` from `cad_pdf_rebuilder.core`.
- No test suite, linter, or build step is configured.

Target Python 3.10–3.12 (rapidocr-onnxruntime lags newer versions). The project is Windows-only in practice (Tk GUI, ZWCAD path probing, `simsun.ttc`).

## Architecture

Two-file package `cad_pdf_rebuilder/`:

- `core.py` — pure pipeline, no UI. Entry points: `rebuild_pdf` → `rebuild_many`. Pipeline per PDF:
  1. `build_dxf`: open PDF with PyMuPDF, create an `ezdxf` R2018 doc with layers `0` (vectors, white) and `1` (OCR text, red, style `宋体`/`simsun.ttc`). For each page, walk `page.get_drawings()` ops (`l`/`re`/`c`/`m`/`qu`) and emit `LWPOLYLINE`/`LINE` on layer `0`. Pages are stacked vertically in modelspace with `gap` between them (`y_offset = -(page_h + gap) * page_index`).
  2. Text layer: `extract_text_items` honors `force_ocr` (default True). OCR path renders the page at `render_dpi` and runs `rapidocr_onnxruntime.RapidOCR`; non-OCR path uses `page.get_text("dict")` spans. Each `TextItem` becomes a DXF `TEXT` entity with `MIDDLE_CENTER` alignment on layer `1`.
  3. `convert_dxf_to_dwg`: if `find_zwcad()` locates ZWCAD 2025/2026 (hardcoded candidate paths in `core.find_zwcad`), drive it via a temp `.scr` script (`FILEDIA 0`/`SAVEAS 2018`/`QUIT`) launched with `/b`, poll up to 120 s for the temp DWG, then move it next to the DXF. Falls back to DXF-only silently when ZWCAD is absent.

- `app.py` — Tk GUI wrapper. Runs `rebuild_many` on a worker thread; progress messages flow through a `queue.Queue` drained by `self.after(150, ...)` so Tk stays on the main thread. All user-facing options map 1:1 to `RebuildOptions` fields.

### Coordinate system

PDF Y axis is top-down; CAD is bottom-up. All conversions go through `cad_point(point, page_h, y_offset, scale)` which flips Y and applies the global `scale` (default `0.4989286`, exposed in the GUI). When adding new geometry types, route them through `cad_point` / `rect_points` / `flatten_curve` rather than computing coords inline — otherwise the vector layer will drift relative to the text layer.

### Lineweights

`valid_lineweight` snaps `width * scale * 35` to the discrete DXF lineweight enum. Don't pass raw widths to `dxfattribs={"lineweight": ...}`; ezdxf will reject non-enum values.

### DWG conversion caveats

- `convert_dxf_to_dwg` writes scripts under `%TEMP%/pdf_two_layer_cad_rebuilder/` keyed by a sha1 of the DXF path, and uses `Popen` (not `run`) — it polls the filesystem instead of waiting on the process, because ZWCAD's `/b` script mode can hang on dialog edge cases.
- If the target DWG is locked (CAD still holds it), the function returns the temp path so the caller can surface a manual-copy message rather than failing.

## Notes for future changes

- `core.py` is small (~350 lines) and intentionally flat. Prefer extending the existing dispatch in `build_dxf`'s drawing-op loop over splitting it across files.
- The default font `simsun.ttc` and style name `宋体` are written into the DXF style table. Changing them requires either an installed font with that filename or editing `RebuildOptions.text_font` / `text_style` together.
- The repo currently has uncommitted edits to `cad_pdf_rebuilder/core.py` on `main`.
