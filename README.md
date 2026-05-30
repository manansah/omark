# OMark - Local Document to Markdown Converter

OMark is a sleek, local batch document-to-markdown converter built with Python's standard `tkinter` framework, powered by Microsoft's `markitdown` library and a local Ollama instance running the vision-capable `qwen3.5:9b` model (or compatible multimodal models).

It is optimized for layout-aware OCR with native support for mixed English and Hindi/Devanagari scripts.

## Features
- **Modern Dark UI**: Flat-designed Tkinter layout optimized for high DPI Windows screens.
- **Threaded Execution**: Conversions execute in a non-blocking background worker thread, ensuring the GUI remains fully responsive, fluid, and draggable.
- **Start / Pause / Stop Controls**: Safely pause or stop batch processing queues cooperatively between page and file boundaries.
- **Dual Progress Bars**: 
  - *Overall Batch Progress*: determinate tracker for total file completions.
  - *Active File OCR Status*: indeterminate heartbeat indicator showing ongoing GPU/OCR page rendering.
- **Force Visual OCR (PDF to Image)**: Automatically renders PDF document pages to high-resolution images via `pypdfium2` and feeds them page-by-page to the vision model, bypassing PDF font encoding bugs and transcribing mixed Devanagari text visually.
- **OCR Prompt Tuning**: Direct control over the transcription instructions sent to the vision model.
- **Endpoint Auto-Sanitization**: Automatically appends the `/v1` compatibility suffix for bare Ollama URLs.
- **Robust Exception Handling**: Captures network timeouts, missing files, or GPU VRAM allocation errors file-by-file without aborting the rest of the queue.

## Supported Formats
- Documents: `.pdf`, `.docx`, `.pptx`, `.xlsx`
- Images: `.png`, `.jpg`, `.jpeg`

## Installation

1. Install Python 3.10+
2. Pull your vision model via Ollama (e.g., `qwen3.5:9b` or `qwen2.5-vision:7b`):
   ```powershell
   ollama pull qwen3.5:9b
   ```
3. On Windows, run the included dependency installer. It installs Tesseract OCR,
   FFmpeg, and Python dependencies for PDF, Word, Excel, PowerPoint, and optional
   audio conversion into a local `.venv`:
   ```powershell
   .\install_dependencies.bat
   ```

   To install only the Python dependencies manually:
   ```powershell
   pip install -r requirements.txt
   ```

## Usage

Run the desktop application:
```powershell
.\run_omark.bat
```
Select a conversion mode:
- **Smart Local OCR**: recommended offline mode. Uses embedded PDF text and native table
  geometry where available, then automatically falls back to Tesseract OCR for scanned
  PDFs and images.
- **Tesseract OCR**: forces local OCR for PDF pages and images. The installer adds English
  and Hindi OCR support.
- **Ollama Vision**: layout-aware visual OCR through a local multimodal Ollama model.
- **Native extraction**: embedded PDF text extraction without OCR.

Word (`.docx`), Excel (`.xlsx`), and PowerPoint (`.pptx`) files are parsed directly
through MarkItDown regardless of the selected PDF backend.

Source documents can be selected with **Browse Files** or dragged from Windows Explorer
onto the source-file list.

Tesseract PDF OCR automatically improves scan contrast, corrects sideways and
upside-down pages, applies small deskew corrections when confidence improves, and
converts bordered scan tables into Markdown tables cell-by-cell.

Enable **Run final output through MarkItDown** to pass the generated Markdown through
MarkItDown once more before saving. This is optional and disabled by default.
