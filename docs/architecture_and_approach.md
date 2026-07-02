# Legal ETL Pipeline: Architecture & Approach

This document provides a detailed overview of the design architecture, processing approaches, and technical decisions implemented for the Pakistani Legal Dataset ingestion pipeline. The system processes heterogeneous legal documents (judicial judgments and statutory codes), normalizes them into a unified format, chunkifies them using specialized legal-specific strategies, and indexes them into Weaviate for Retrieval-Augmented Generation (RAG).

---

## 1. System Architecture

The pipeline follows a **Medallion Data Warehouse** architecture, separating data by its processing state. The entire orchestration is containerized using Docker and scheduled via Apache Airflow.

```mermaid
flowchart TD
    subgraph Raw Ingest Queue
        SRC_BHC[Balochistan HC PDFs]
        SRC_PHC[Peshawar HC PDFs]
        SRC_SC[Supreme Court PDFs]
        SRC_CODES[Legal Codes JSONLs]
    end

    subgraph Data Warehouse Stages
        RAW[1. raw/ - Unprocessed Data]
        ARC[2. archive/ - Successfully Parsed]
        QRT[3. quarantine/ - Stubs & Error Files]
    end

    subgraph Orchestrated Execution (Airflow)
        T1[Scraper Sync Task]
        T2[Parsing & Heuristics Task]
        T3[Weaviate Batch Load Task]
    end

    subgraph Vector Database
        WV[(Weaviate DB)]
    end

    SRC_BHC & SRC_PHC & SRC_SC & SRC_CODES --> RAW
    RAW --> T2
    T2 -->|On Success| ARC
    T2 -->|On Failure / <1KB Stub| QRT
    T2 -->|JSONL Cache| PROCESSED[(processed/ Cache)]
    PROCESSED --> T3
    T3 -->|Batch Load| WV
```

---

## 2. Why JSON Lines (JSONL) Format?

In production data engineering, JSON Lines (JSONL) is preferred over standard JSON for several key reasons:
1. **Memory Efficiency (Streaming)**: Standard JSON requires loading the entire file (a large array of objects) into memory to parse it, causing scale bottlenecks. JSONL enables streaming documents or chunks line-by-line (`for line in file:`), maintaining a constant $O(1)$ RAM footprint regardless of dataset size.
2. **Crash Resilience**: If a process crashes mid-execution, a JSONL file remains completely valid up to the last successfully written line. Standard JSON becomes corrupted and unparsable if it is truncated or missing its closing brackets `]`.
3. **Append-Only Writing**: Writing output caches is an append-only operation, avoiding expensive read-and-rewrite processes as new documents are processed.
4. **Simple Parallelization**: Because each line is a self-contained, valid JSON object, datasets can be split easily by line boundaries to distribute workloads across multiple cores or database batch workers.

---

## 3. Medallion-Style Data Lifecycle

The pipeline maps directly to the standard medallion data architecture stages (Bronze, Silver, Gold) to guarantee structural purity and clean lifecycle tracking:

### 🥉 Bronze Stage (Raw Data Store)
*   **Location**: `data_warehouse/raw/`
*   **Description**: Holds original, unprocessed source files (PDFs, raw CSV case indices, and original statutory JSONLs).
*   **Lifecycle Management**: Once a file is processed successfully, the ETL moves it out of `raw/` and into `data_warehouse/archive/` to keep the ingestion queue clean. Corrupted files or failed scraper stubs are segregated into `data_warehouse/quarantine/`.

### 🥈 Silver Stage (Normalized & Cleansed Data)
*   **Location**: `processed/processed_documents.jsonl`
*   **Description**: This represents our cleansed, normalized database. Standard watermarks are stripped, heuristics (advocates, laws, outcomes) are extracted, and documents from all sources are conformed to a unified schema.

### 🥇 Gold Stage (Vectorized & Search-Optimized Data)
*   **Location**: `processed/processed_chunks.jsonl` (local cache) and **Weaviate Vector DB** (`LegalChunk` collection).
*   **Description**: Contains the vectorized chunks with injected global document contexts, fully prepared and indexed for semantic search and RAG queries.

---

## 4. Specialized Chunking Strategy

Standard text chunking (e.g., splitting by fixed character counts) damages legal document semantics. This system implements two tailored chunking algorithms:

### A. Statutory Laws & Codes (Logical Boundaries)
*   **Approach**: Splits text strictly on structural section boundaries (`section_XXXX`).
*   **Rules**:
    *   If a section is short (< 600 words), it is kept intact.
    *   If a section is very long, it is split recursively on paragraph breaks (`\n\n`), ensuring that no sentence is broken across chunks.

### B. Court Judgments (Paragraph Sliding Window + Context Injection)
*   **Approach**: Paragraph-based sliding window with global context injection.
*   **Context Injection**: Every generated chunk is prepended with a structured text header (context string) containing crucial metadata:
    ```text
    [Document Context - Case Title: {case_title} | Court: {court} | Judge: {author_judge} | Date: {order_date}]
    ```
    This ensures that when a vector search retrieves a chunk, the LLM immediately knows the context of the ruling (who the judge was, which court made the ruling, and when).
*   **Sliding Window**: Paragraphs are accumulated until they hit a window size of ~600 words, with an overlap of ~150 words.

---

## 5. Unified Schema & Heuristics

All sources map to a standard metadata schema:

### Pydantic Schemas

*   **`Document`**: The raw text document.
*   **`Chunk`**: The output vector chunk.
*   **`JudgmentMetadata`**: Case-specific metadata (case ID, case title, case number, court, author judge, judgment type, date, outcome, referenced laws, advocates).
*   **`LawMetadata`**: Statutory metadata (law ID, law name, section number, section title).

### Heuristic Metadata Extraction

The extraction module (`preprocessing/extractor.py`) applies NLP and regex-based heuristics to extract missing metadata:
1.  **Referenced Laws**: Searches case bodies for patterns like `Section 302 PPC`, `Article 199`, or `Section 249-A CrPC` and normalizes them into lists of standard law keys.
2.  **Advocates**: Identifies names prefixing `Advocate for` or following `Mr./Ms./Mrs.` in header metadata and matches them with their representing clients.
3.  **Outcomes**: Detects outcome classifications (e.g. *Allowed*, *Dismissed*, *Accepted*, *Acquitted*, *Bail Granted*, *Bail Refused*) by inspecting the final paragraphs of the text.
4.  **Supreme Court Decoders**:
    *   **Case Number**: Decoded from SC filenames (e.g., `c.a._1032_2018.pdf` ➔ `Civil Appeal No. 1032 of 2018`).
    *   **Case Title**: Extracted via `Petitioner Versus Respondent` body matching.
    *   **Judge Name**: Extracted from parent judge folder.

---

## 6. Docker Compose & Services

The pipeline runs in a multi-container Docker cluster:

| Service | Port | Description |
| :--- | :--- | :--- |
| **`postgres`** | Internal | Airflow metadata database. |
| **`weaviate`** | `8080` | Vector Database storing embeddings using the OpenAI vectorizer. |
| **`airflow-webserver`** | `8081` | Web GUI for Airflow. |
| **`airflow-scheduler`** | Internal | Monitors, schedules, and runs the DAG steps. |

### Volumes
Local directory mounts are configured so that file structures are synchronized instantly:
*   `./data_warehouse` ➔ `/opt/airflow/data_warehouse`
*   `./processed` ➔ `/opt/airflow/processed`
*   `./preprocessing` ➔ `/opt/airflow/dags/preprocessing`
*   `./dags` ➔ `/opt/airflow/dags`

---

## 7. Pipeline Execution Guide

1.  **Start Services**:
    ```bash
    docker compose up --build -d
    ```
2.  **Trigger processing**:
    Open the Airflow GUI at `http://localhost:8081` (credentials: `airflow` / `airflow`), enable `legal_data_etl_pipeline`, and trigger the run.
3.  **Verify outputs**:
    *   Verify files have migrated from `data_warehouse/raw/` to `data_warehouse/archive/`.
    *   Verify local caches are created at `processed/processed_documents.jsonl` and `processed_chunks.jsonl`.
    *   Query Weaviate's `LegalChunk` collection to verify vector indexing.
