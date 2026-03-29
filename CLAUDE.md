# MCP Tools

A collection of MCP servers. See `README.md` for an overview of each server.

## Running the document server

The document processing server (`server_documents.py`) uses marker-pdf, which runs on
PyTorch and is GPU-backend agnostic. The Python code works with both ROCm and CUDA —
only the launch script differs.

Each GPU backend has its own start script that sets up the required environment variables
before launching the server:

- **ROCm:** `./start_documents_rocm.sh` — sets ROCm/HIP env vars for lilbuddy's Radeon 8060S (gfx1151)
- **CUDA:** No script yet. Add a `start_documents_cuda.sh` when needed.

The server binds to `127.0.0.1:8200` (streamable-http) and is reverse-proxied by Caddy on `:8020`.

First run after reboot is slow (~4 min) as ROCm compiles GPU kernels for gfx1151.
New batch sizes also trigger kernel compilation on first encounter.

## Document processing modes

Two processing modes via the `mode` parameter:

- **fast** (default) — text extraction, structural analysis, equation LaTeX, and tables.
  Skips LLM-based processors and image extraction.
- **full** — everything marker-pdf offers, including LLM refinement and image extraction.

## Deployment

The document server runs as a systemd user service on lilbuddy:

```bash
systemctl --user status document-processing
systemctl --user restart document-processing
```

## Package management

Use `uv`, not pip. The venv is at `.venv/`.

## Key architectural notes

- marker-pdf's pipeline: layout detection -> OCR -> processors (in order) -> renderer
- Inline math ($...$) is captured during regular text OCR via surya's `math_mode` parameter
- Display math ($$...$$) requires `EquationProcessor` — it runs dedicated surya OCR on
  detected equation blocks that are skipped by the regular text OCR pass
- Table recognition uses three models: TableRecPredictor, DetectionPredictor, RecognitionPredictor
- ROCm kernel compilation is triggered per unique batch size; subsequent runs use cached kernels
- `FAST_PROCESSORS` list in `server_documents.py` is curated and tested; key fixes applied:
  - `pageheader` -> `page_header`, `blankpage` -> `blank_page` (module naming)
  - Added `EquationProcessor` (display-style equations were silently dropped without it)
  - Added `TableProcessor` (minimal overhead: 2-22% depending on table density)

## Known limitations

- No benchmarking of `"full"` mode on ROCm yet (only fast mode tested)
- LLM-based processors in full mode require an external LLM service — not configured
- The `force_ocr` parameter is ignored in fast mode (always False)
- No integration tests beyond manual PDF conversion
