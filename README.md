# ⚖️ BarristerBot — ETL & Data Pipeline

> **Part of the BarristerBot ecosystem** · [Webapp Repository →](https://github.com/omerkhanjadoon/barristerbot-web)

This repository contains the **data engineering backbone** of BarristerBot — an AI-based legal assistant for the people of Pakistan. It handles everything from scraping raw court judgments to producing clean, chunked, vector-indexed documents ready for RAG (Retrieval-Augmented Generation).

> **Note:** The AI chat interface and user-facing webapp live in a separate repository. This repo is solely responsible for data ingestion, transformation, and indexing.

---

## 🎯 What This Repo Does

BarristerBot's AI needs a high-quality, structured legal knowledge base to function. This pipeline:

1. **Scrapes** thousands of judicial judgments from Pakistan's superior courts (PHC, BHC, Supreme Court)
2. **Parses** raw PDFs, extracting structured metadata via NLP heuristics
3. **Chunks** the extracted text using a legal-domain sliding-window strategy
4. **Validates** all output against strict Pydantic schemas
5. **Indexes** vector embeddings into Weaviate for semantic search
6. **Orchestrates** the full workflow via Apache Airflow with retries and logging

---

## 🏗️ Pipeline Architecture

```
 ┌──────────────────────────────────────────────────────────────────┐
 │                    DATA INGESTION LAYER                          │
 │    data_scrapper/scraper.py (PHC)  +  scraper_bhc.py (BHC)      │
 └─────────────────────────┬────────────────────────────────────────┘
                           │ Raw PDFs
                           ▼
 ┌──────────────────────────────────────────────────────────────────┐
 │              MEDALLION STORAGE  (data_warehouse/)                │
 │   raw/  ──►  [ETL Processing]  ──►  archive/  or  quarantine/   │
 └─────────────────────────┬────────────────────────────────────────┘
                           │
                           ▼
 ┌──────────────────────────────────────────────────────────────────┐
 │           PREPROCESSING PIPELINE  (preprocessing/)               │
 │  extractor.py → chunker.py → schemas.py → pipeline.py           │
 └─────────────────────────┬────────────────────────────────────────┘
                           │ JSONL cache (git-ignored)
                           ▼
 ┌──────────────────────────────────────────────────────────────────┐
 │              VECTOR INDEX  ·  Weaviate                           │
 │  Embeddings indexed  ──►  Consumed by BarristerBot Webapp        │
 └──────────────────────────────────────────────────────────────────┘
```

---

## 🗂️ Directory Structure

```text
barristerbot-etl/
├── dags/
│   └── legal_etl_dag.py          # Apache Airflow master ETL orchestration DAG
├── data_scrapper/
│   ├── scraper.py                # Peshawar High Court (PHC) judgment scraper
│   └── scraper_bhc.py            # Balochistan High Court (BHC) judgment scraper
├── preprocessing/
│   ├── extractor.py              # PDF parsing, metadata & NLP heuristic extraction
│   ├── chunker.py                # Specialized legal sliding-window chunkers
│   ├── schemas.py                # Pydantic schema models for validated documents
│   └── pipeline.py               # CLI pipeline entrypoint
├── data_warehouse/
│   ├── raw/                      # Raw input PDFs (BHC, PHC, Supreme Court) [git-ignored]
│   ├── archive/                  # Successfully processed source files [git-ignored]
│   └── quarantine/               # Stubs (<1 KB) and corrupted/unreadable files [git-ignored]
├── docs/
│   └── architecture_and_approach.md  # Detailed architecture & design rationale
├── tests/                        # Integration & unit tests
├── Dockerfile                    # Container image definition
├── docker-compose.yml            # Orchestrates Airflow + Weaviate + PostgreSQL
├── migrate_structure.py          # Safe script to migrate inputs to Medallion layout
└── .env                          # Environment variables (not committed)
```

---

## 🚀 Getting Started

### Prerequisites

| Tool | Version |
|---|---|
| Docker & Docker Compose | Latest |
| Python | 3.10+ |

### 1. Configure Environment

```bash
cp .env.example .env
# Edit .env with your API keys and Weaviate config
```

### 2. Spin Up Services

Start PostgreSQL (Airflow metastore), Weaviate (vector DB), and Apache Airflow:

```bash
docker compose up --build -d
```

### 3. Trigger the Pipeline

1. Open Airflow at [http://localhost:8081](http://localhost:8081)  
   *(Credentials: `airflow` / `airflow`)*
2. Toggle the `legal_data_etl_pipeline` DAG to **Active**.
3. Trigger the DAG manually to begin ingestion.

---

## 🕷️ Data Scraping

Dedicated scrapers are included for each court source. Both support **resume capability** — interrupted runs pick up where they left off.

| Court | Script | Coverage |
|---|---|---|
| Peshawar High Court (PHC) | `data_scrapper/scraper.py` | All reported judgments |
| Balochistan High Court (BHC) | `data_scrapper/scraper_bhc.py` | All judges, 2005–present |

```bash
# Run scrapers independently
python data_scrapper/scraper.py        # PHC
python data_scrapper/scraper_bhc.py   # BHC
```

---

## ⚙️ Pipeline Stages

### 1. Extraction (`extractor.py`)
Parses raw PDFs using heuristic NLP to extract structured metadata: court name, citation, bench composition, judgment date, petitioner/respondent names. Flags stubs and corrupted files for quarantine.

### 2. Chunking (`chunker.py`)
Applies a **legal-domain sliding-window chunker** tuned for long-form judicial text. Preserves paragraph boundaries, section headings, and citation context to maintain semantic coherence in retrieved chunks.

### 3. Schema Validation (`schemas.py`)
All extracted documents and chunks are validated against strict **Pydantic models** before writing to cache, ensuring the vector index receives clean, typed data.

### 4. Orchestration (`dags/legal_etl_dag.py`)
Apache Airflow DAG coordinates the full pipeline — managing retries, task dependencies, and structured logging.

### 5. Vector Indexing (Weaviate)
Processed chunks are embedded and indexed into **Weaviate** for fast semantic search. This index is the data source consumed by the BarristerBot webapp for RAG-powered responses.

---

## 🧪 Local Testing

### Pipeline Execution
Run the pipeline locally without Docker:

```bash
PYTHONPATH=. python3 preprocessing/pipeline.py --help
```

### Running the Test Suite
The repository includes a comprehensive suite of unit and integration tests under the `tests/` directory:

*   **`test_schemas.py`**: Unit tests verifying Pydantic schema validation for metadata types, documents, and chunks.
*   **`test_chunker.py`**: Unit tests confirming document type context prefix headers, metadata flattening (for Weaviate query filters), and paragraph/section sliding window splitting algorithms.
*   **`test_extractor.py`**: Unit tests validating NLP text heuristics (advocate extraction, outcome classification, law citations) and watermark cleansing.
*   **`test_integration.py`**: End-to-end integration test creating temp file environments, compiling dummy PDFs (> 1KB) & metadata CSVs, orchestrating a complete pipeline run, validating outputs, and testing Medallion folder movements.

To execute the test suite, run:

```bash
python3 -m pytest tests/ -v
```

---

## 📚 Technical Documentation

- [Architecture & Approach](docs/architecture_and_approach.md) — Medallion stages, chunking strategy, NLP heuristics, and schema design.

---

## 🔗 Related Repositories

| Repository | Description |
|---|---|
| **barristerbot-etl** *(this repo)* | Data scraping, ETL pipeline & vector indexing |
| **barristerbot-web** | AI chat interface & user-facing webapp |

---

## 🛣️ ETL Roadmap

- [ ] Supreme Court of Pakistan scraper
- [ ] Federal Shariat Court coverage
- [ ] Urdu OCR support for scanned legacy judgments
- [ ] Incremental / delta ingestion (only process new judgments)
- [ ] Automated data quality dashboards

---

## 📄 License

MIT License. See [LICENSE](LICENSE) for details.

---

## 👤 Author

**Omer Khan Jadoon** — Building AI tools to democratize access to justice in Pakistan.
