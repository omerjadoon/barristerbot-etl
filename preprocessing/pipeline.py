import os
import json
import argparse
from preprocessing.extractor import LegalExtractor
from preprocessing.chunker import LegalChunker

def run_pipeline(pdf_dir: str, 
                 csv_path: str, 
                 jsonl_dir: str, 
                 output_dir: str, 
                 peshawar_pdf_dir: str = None,
                 peshawar_csv_path: str = None,
                 sc_dir: str = None,
                 weaviate_url: str = None,
                 archive_dir: str = None,
                 quarantine_dir: str = None,
                 chunks_output_dir: str = None):  # 🥇 Gold stage dir; defaults to output_dir
    print("Initializing Legal Data ETL Pipeline...")
    os.makedirs(output_dir, exist_ok=True)
    # Gold stage: chunks go to their own directory if specified (Medallion layout)
    _chunks_dir = chunks_output_dir if chunks_output_dir else output_dir
    os.makedirs(_chunks_dir, exist_ok=True)

    extractor = LegalExtractor(
        pdf_dir=pdf_dir, 
        csv_path=csv_path, 
        jsonl_dir=jsonl_dir,
        peshawar_pdf_dir=peshawar_pdf_dir,
        peshawar_csv_path=peshawar_csv_path,
        sc_dir=sc_dir,
        archive_dir=archive_dir,
        quarantine_dir=quarantine_dir
    )
    chunker = LegalChunker(target_word_size=600, overlap_word_size=150)
    
    documents_count = 0
    chunks_count = 0
    
    doc_out_path = os.path.join(output_dir, "processed_documents.jsonl")     # 🥈 Silver
    chunk_out_path = os.path.join(_chunks_dir, "processed_chunks.jsonl")       # 🥇 Gold
    
    print("Extraction targets:")
    print(f"  BHC PDFs: {pdf_dir}")
    print(f"  BHC CSV: {csv_path}")
    print(f"  PHC PDFs: {peshawar_pdf_dir}")
    print(f"  PHC CSV: {peshawar_csv_path}")
    print(f"  SC PDFs: {sc_dir}")
    print(f"  Laws JSONL: {jsonl_dir}")
    print(f"  Archive folder: {archive_dir}")
    print(f"  Quarantine folder: {quarantine_dir}")
    print(f"Writing outputs to:")
    print(f"  🥈 Silver (Documents): {doc_out_path}")
    print(f"  🥇 Gold (Chunks):     {chunk_out_path}")

    with open(doc_out_path, "w", encoding="utf-8") as f_docs, open(chunk_out_path, "w", encoding="utf-8") as f_chunks:
        # 1. Process Laws
        print("\nProcessing Legal Code (laws)...")
        for doc in extractor.parse_laws():
            documents_count += 1
            f_docs.write(doc.model_dump_json() + "\n")
            
            chunks = chunker.chunk_document(doc)
            for chunk in chunks:
                chunks_count += 1
                f_chunks.write(chunk.model_dump_json() + "\n")
                
        # 2. Process BHC Judgments
        if pdf_dir and csv_path:
            print("\nProcessing Balochistan High Court Judgments...")
            for doc in extractor.parse_judgments():
                documents_count += 1
                f_docs.write(doc.model_dump_json() + "\n")
                
                chunks = chunker.chunk_document(doc)
                for chunk in chunks:
                    chunks_count += 1
                    f_chunks.write(chunk.model_dump_json() + "\n")

        # 3. Process PHC Judgments
        if peshawar_pdf_dir and peshawar_csv_path:
            print("\nProcessing Peshawar High Court Judgments...")
            for doc in extractor.parse_peshawar_judgments():
                documents_count += 1
                f_docs.write(doc.model_dump_json() + "\n")
                
                chunks = chunker.chunk_document(doc)
                for chunk in chunks:
                    chunks_count += 1
                    f_chunks.write(chunk.model_dump_json() + "\n")

        # 4. Process SC Judgments
        if sc_dir:
            print("\nProcessing Supreme Court Judgments...")
            for doc in extractor.parse_sc_judgments():
                documents_count += 1
                f_docs.write(doc.model_dump_json() + "\n")
                
                chunks = chunker.chunk_document(doc)
                for chunk in chunks:
                    chunks_count += 1
                    f_chunks.write(chunk.model_dump_json() + "\n")
                
    print("\nETL Pipeline Preprocessing Phase Complete!")
    print(f"  - Total unified documents parsed: {documents_count}")
    print(f"  - Total chunks generated: {chunks_count}")
    
    # 5. Optional Weaviate Ingestion
    if weaviate_url:
        ingest_to_weaviate(chunk_out_path, weaviate_url)
    else:
        print("\n[INFO] Weaviate URL not provided. Chunks saved locally. Set --weaviate_url to trigger auto-ingestion.")

def ingest_to_weaviate(chunks_file_path: str, weaviate_url: str, api_key: str = None):
    """
    Ingests flat chunks into Weaviate using the v3 Client (weaviate-client==3.x).
    Supports both local (anonymous) and Weaviate Cloud (API key) connections.
    """
    print(f"\nConnecting to Weaviate instance at {weaviate_url} for ingestion...")

    try:
        import weaviate as _weaviate
        client_installed = True
    except ImportError:
        client_installed = False
        print("[WARNING] Weaviate python client package is not installed.")
        print("  Please install it: pip install weaviate-client")

    if not client_installed:
        print(f"Skipping DB write (schema ready to target Weaviate instance: {weaviate_url})")
        return

    print(f"Using Weaviate V3 Python SDK ({_weaviate.__version__})...")
    is_cloud = api_key is not None
    print(f"  Mode: {'☁️  Weaviate Cloud (authenticated)' if is_cloud else '🏠 Local (anonymous)'}")

    try:
        auth = _weaviate.AuthApiKey(api_key=api_key) if is_cloud else None
        client = _weaviate.Client(url=weaviate_url, auth_client_secret=auth)

        collection_name = "LegalChunk"

        # ── Schema ───────────────────────────────────────────────────────────
        existing_classes = [c["class"] for c in client.schema.get().get("classes", [])]
        if collection_name not in existing_classes:
            print(f"Creating Weaviate class '{collection_name}'...")
            schema = {
                "class": collection_name,
                "vectorizer": "none",  # Store raw text now; add embeddings later via a separate job
                "properties": [
                    {"name": "chunk_id",        "dataType": ["text"]},
                    {"name": "doc_id",          "dataType": ["text"]},
                    {"name": "doc_type",        "dataType": ["text"]},
                    {"name": "text",            "dataType": ["text"]},
                    {"name": "chunk_index",     "dataType": ["int"]},
                    {"name": "case_title",      "dataType": ["text"]},
                    {"name": "case_number",     "dataType": ["text"]},
                    {"name": "court",           "dataType": ["text"]},
                    {"name": "author_judge",    "dataType": ["text"]},
                    {"name": "judgment_type",   "dataType": ["text"]},
                    {"name": "order_date",      "dataType": ["text"]},
                    {"name": "outcome",         "dataType": ["text"]},
                    {"name": "referenced_laws", "dataType": ["text[]"]},
                    {"name": "advocates",       "dataType": ["text[]"]},
                    {"name": "law_id",          "dataType": ["text"]},
                    {"name": "law_name",        "dataType": ["text"]},
                    {"name": "section_number",  "dataType": ["text"]},
                    {"name": "section_title",   "dataType": ["text"]},
                ],
            }
            client.schema.create_class(schema)
            print(f"  ✅ Class '{collection_name}' created.")
        else:
            print(f"  ℹ️  Class '{collection_name}' already exists — skipping creation.")

        # ── Batch ingestion ──────────────────────────────────────────────────
        print("Uploading chunks to Weaviate (batch mode)...")
        ingested = 0
        errors   = 0

        with client.batch as batch:
            batch.batch_size        = 200
            batch.dynamic           = True
            batch.timeout_retries   = 3
            batch.connection_error_retries = 3

            with open(chunks_file_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue

                    chunk_data = json.loads(line)
                    properties = {
                        "chunk_id":    chunk_data["chunk_id"],
                        "doc_id":      chunk_data["doc_id"],
                        "doc_type":    chunk_data["doc_type"],
                        "text":        chunk_data["text"],
                        "chunk_index": chunk_data["chunk_index"],
                    }

                    meta = chunk_data.get("metadata", {})
                    for k, v in meta.items():
                        if k == "advocates" and isinstance(v, list):
                            formatted = []
                            for adv in v:
                                if isinstance(adv, dict):
                                    name = adv.get("name", "").strip()
                                    role = adv.get("role", "").strip()
                                    formatted.append(f"{name} ({role})" if role else name)
                                else:
                                    formatted.append(str(adv))
                            properties[k] = formatted
                        else:
                            properties[k] = v

                    batch.add_data_object(
                        data_object=properties,
                        class_name=collection_name,
                        uuid=chunk_data["chunk_id"],
                    )
                    ingested += 1

                    if ingested % 1000 == 0:
                        print(f"  … {ingested} chunks queued so far")

        print(f"\n✅ Ingestion complete — {ingested} chunks sent to Weaviate.")
        print(f"   Collection: {collection_name} @ {weaviate_url}")

    except Exception as e:
        print(f"[ERROR] Weaviate ingestion failed: {e}")
        raise

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Legal Dataset ETL Pipeline")
    parser.add_argument("--pdf_dir", default="data_warehouse/raw/bhc", help="Directory of BHC case PDFs")
    parser.add_argument("--csv_path", default="data_warehouse/raw/bhc/metadata.csv", help="Path to BHC metadata CSV")
    parser.add_argument("--jsonl_dir", default="data_warehouse/raw/legal_codes", help="Directory of JSONL legal codes")
    parser.add_argument("--output_dir", default="processed", help="Output folder for JSONL caches")
    parser.add_argument("--peshawar_pdf_dir", default="data_warehouse/raw/phc", help="Directory of Peshawar case PDFs")
    parser.add_argument("--peshawar_csv_path", default="data_warehouse/raw/phc/metadata.csv", help="Path to Peshawar metadata CSV")
    parser.add_argument("--sc_dir", default="data_warehouse/raw/sc", help="Directory of Supreme Court judge folders containing PDFs")
    parser.add_argument("--archive_dir", default="data_warehouse/archive", help="Directory for successfully processed files")
    parser.add_argument("--quarantine_dir", default="data_warehouse/quarantine", help="Directory for stubs and failed parsing attempts")
    parser.add_argument("--weaviate_url", default=None, help="Weaviate DB endpoint (e.g. http://localhost:8080)")
    
    args = parser.parse_args()
    run_pipeline(
        pdf_dir=args.pdf_dir,
        csv_path=args.csv_path,
        jsonl_dir=args.jsonl_dir,
        output_dir=args.output_dir,
        peshawar_pdf_dir=args.peshawar_pdf_dir,
        peshawar_csv_path=args.peshawar_csv_path,
        sc_dir=args.sc_dir,
        archive_dir=args.archive_dir,
        quarantine_dir=args.quarantine_dir,
        weaviate_url=args.weaviate_url
    )
