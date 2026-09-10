---
created: '2026-07-28T16:26:50.641508'
embedding_model: all-MiniLM-L6-v2
id: 6f874ddc
links: []
para: Projects
raw_ref: raw/20260728_162650_6f874ddc.md
summary: 'SecondSelf: personal AI second brain for capturing, classifying, graphing
  knowledge.'
tags:
- ai
- secondbrain
- knowledge
- graph
- personal
---

# SecondSelf

Your personal AI second brain — capture anything, let AI organize it, explore it as a graph, and ask questions over your own knowledge.

## Status

| Phase | Name | Status |
|-------|------|--------|
| 0 | Foundation | Done |
| 1 | The Archivist (capture) | Done |
| 2 | The Librarian (classify + link) | Not started |
| 3 | The Cartographer (graph) | Not started |
| 4 | The Oracle (ask + deploy) | Not started |

## Setup

1. **Clone and enter the project**
   ```bash
   cd Second-Self
   ```

2. **Create a virtual environment (Python 3.10+)**
   ```bash
   python -m venv .venv
   .venv\Scripts\activate        # Windows
   # source .venv/bin/activate   # macOS / Linux
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure secrets** (needed from Phase 2 onward)
   ```bash
   copy .env.example .env        # Windows
   # cp .env.example .env        # macOS / Linux
   ```
   Add your [Groq API key](https://console.groq.com/) to `.env`.

5. **Verify setup**
   ```bash
   python -c "import config; print('OK')"
   ```

## Project layout

```
Second-Self/
├── raw/           # Raw captures (Phase 1)
├── wiki/          # Classified, linked notes (Phase 2)
├── data/          # graph.json and other exports (Phase 3)
├── embeddings/    # Cached note vectors (Phase 2)
├── config.py      # Shared paths and settings
├── docs/          # Architecture and implementation plans
└── requirements.txt
```

## Usage (Phase 1)

Capture notes, links, and files into `raw/`:

```bash
python capture.py "My idea about building a RAG system"
python capture.py --link https://example.com/article
python capture.py --file ./documents/resume.pdf
echo "Quick thought from terminal" | python capture.py --stdin
```

Each capture gets a timestamped filename (`{YYYYMMDD}_{HHMMSS}_{id}.{ext}`) and an optional `{id}.meta.json` sidecar.

## Documentation

- [Problem Statement](docs/Problem_Statement.md)
- [Architecture](docs/architecture.md)
- [Implementation Plan](docs/Implementation-plan.md)
- [Edge Cases](docs/edge-case.md)

## License

Personal project — use and adapt as you like.