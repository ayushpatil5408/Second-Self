# SecondSelf

Your personal AI second brain — capture anything, let AI organize it, explore it as a graph, and ask questions over your own knowledge.

## Status

| Phase | Name | Status |
|-------|------|--------|
| 0 | Foundation | Done |
| 1 | The Archivist (capture) | Done |
| 2 | The Librarian (classify + link) | Done |
| 3 | The Cartographer (graph) | Done |
| 4 | The Oracle (ask + deploy) | Done |

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

4. **Configure secrets**
   ```bash
   copy .env.example .env        # Windows
   # cp .env.example .env        # macOS / Linux
   ```
   Add your [Groq API key](https://console.groq.com/) to `.env`.

5. **Verify setup**
   ```bash
   python -c "import config; print('OK')"
   ```

## Project Layout

```
Second-Self/
├── raw/                  # Raw captures (Phase 1)
├── wiki/                 # Classified, linked notes in PARA folders (Phase 2)
│   ├── Projects/
│   ├── Areas/
│   ├── Resources/
│   └── Archives/
├── data/                 # graph.json and export data (Phase 3)
├── embeddings/           # Cached note vectors (Phase 2)
├── docs/                 # System architecture and design specifications
├── .streamlit/           # Streamlit app configuration (Phase 4)
├── config.py             # Shared paths and hyperparameters (Phase 0)
├── capture.py            # Capture pipeline (Phase 1)
├── classify.py           # PARA classification via Groq LLM (Phase 2)
├── link.py               # Auto-linking via Sentence Transformers (Phase 2)
├── pipeline.py           # Orchestrator: classify + link (Phase 2)
├── build_graph.py        # Knowledge graph generator (Phase 3)
├── graph_component.html  # Force-directed graph component (Phase 3)
├── ask.py                # RAG query engine (Phase 4)
├── app.py                # Streamlit UI combining graph & RAG (Phase 4)
└── requirements.txt      # Project dependencies
```

## Quick Reference / Usage

### 1. Capture (Phase 1)
Capture notes, links, and files into `raw/`:
```bash
python capture.py "My idea about building a RAG system"
python capture.py --link https://example.com/article
python capture.py --file ./documents/sample.pdf
echo "Quick thought from terminal" | python capture.py --stdin
```

### 2. Organize & Auto-Link (Phase 2)
Process new captures into PARA-structured markdown and auto-link similar notes:
```bash
# Run incremental pipeline (new captures only)
python pipeline.py

# Or run full reprocess
python pipeline.py --all
```

### 3. Build Knowledge Graph (Phase 3)
Export the interactive graph nodes and edges to `data/graph.json`:
```bash
python build_graph.py
```

### 4. Ask Questions via CLI (Phase 4)
Query your second brain with semantic retrieval + Groq LLM synthesis:
```bash
python ask.py "What projects am I working on?"
python ask.py --scores "What are my notes on machine learning?"
```

### 5. Launch the Web Application (Phase 4)
Start the Streamlit web app to view the interactive graph, stats, and search interface:
```bash
# Second Self
[View Live Website](https://second-self-monster.streamlit.app/)
```

## Documentation

- [Problem Statement](docs/Problem_Statement.md)
- [Architecture](docs/architecture.md)
- [Implementation Plan](docs/Implementation-plan.md)
- [Deployment Plan](docs/deployment-plan.md)
- [Streamlit Deployment](docs/STREAMLIT_DEPLOYMENT.md)
- [Edge Cases](docs/edge-case.md)

## License

Personal project — use and adapt as you like.
