# Vogi Agentic AI Platform

Vogi is a standalone local agent workspace for code, automation, research, documents, and tool-driven project work.

## Run

From this folder:

```bash
python -m uvicorn vogi_agent.Vogi.backend.app:app --host 127.0.0.1 --port 3000 --reload
```

or:

```bash
python -m uvicorn main:app --host 127.0.0.1 --port 3000 --reload
```

or:

```bash
python -m uvicorn backend.app:app --host 127.0.0.1 --port 3000 --reload
```

Open:

```txt
http://127.0.0.1:3000/
```

The root URL, `/agent`, and `/platform` all serve the Vogi workspace.

## Environment

```env
VOGI_MODEL_PROVIDER=ollama
OLLAMA_URL=http://127.0.0.1:11434
VOGI_AGENT_MODEL=gemma3:1b
```

Optional:

```env
OPENAI_API_KEY=your-api-key
VOGI_EDGE_CHANNEL=msedge
VOGI_EDGE_PROFILE=Default
VOGI_TESSERACT_PATH=C:/Program Files/Tesseract-OCR/tesseract.exe
```

## Web Retrieval

Vogi retrieves public HTML, rendered web pages, PDFs, and images through `web_search` and `browse_url`. Install its dependencies for full browser and scanned-document support:

```bash
pip install -r requirements.txt
```

On Windows, rendered browsing uses installed Microsoft Edge. OCR uses Tesseract when installed at `VOGI_TESSERACT_PATH`.

For signed-in pages, open Settings and start an authenticated browser session. Close normal Edge windows first; Vogi opens the existing Edge profile visibly and never closes regular Edge automatically.

## Execution And Connections

Vogi executes `run_shell` commands in PowerShell. The permission selector is enforced by the backend:

- `Safe Mode` allows inspection and read-only database/API operations.
- `Full Access (current user)` allows requested package installation, database changes, and state-changing API requests under the current Windows account. It does not grant Administrator rights or bypass UAC.

Operational tools include `install_package` for `winget`/`pip`, `database_query` for SQLAlchemy-compatible connections, and `http_request` for internal application APIs.

## Focus

This app is Vogi-only: coding agent, dynamic planning, tools, skills, memory, documents, research, and local execution.
