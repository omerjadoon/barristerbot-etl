from datetime import datetime, timedelta
import os
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.operators.bash import BashOperator

# Import our pipeline functions
from preprocessing.pipeline import run_pipeline, ingest_to_weaviate

default_args = {
    'owner': 'airflow',
    'depends_on_past': False,
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
}

# Paths configured relative to the Airflow container filesystem (see docker-compose volumes)
BASE_DIR = "/opt/airflow"
PDF_DIR = os.path.join(BASE_DIR, "data_warehouse/bronze/raw/bhc")
CSV_PATH = os.path.join(BASE_DIR, "data_warehouse/bronze/raw/bhc/metadata.csv")
PESHAWAR_PDF_DIR = os.path.join(BASE_DIR, "data_warehouse/bronze/raw/phc")
PESHAWAR_CSV_PATH = os.path.join(BASE_DIR, "data_warehouse/bronze/raw/phc/metadata.csv")
SC_DIR = os.path.join(BASE_DIR, "data_warehouse/bronze/raw/sc")
JSONL_DIR = os.path.join(BASE_DIR, "data_warehouse/bronze/raw/legal_codes")
ARCHIVE_DIR = os.path.join(BASE_DIR, "data_warehouse/bronze/archive")
QUARANTINE_DIR = os.path.join(BASE_DIR, "data_warehouse/bronze/quarantine")
SILVER_DIR = os.path.join(BASE_DIR, "data_warehouse/silver")   # Normalized docs output
GOLD_DIR = os.path.join(BASE_DIR, "data_warehouse/gold")       # Vector chunks output
WEAVIATE_URL = os.environ.get("WEAVIATE_URL", "http://weaviate:8080")
WEAVIATE_API_KEY = os.environ.get("WEAVIATE_API_KEY", None)

def run_preprocessing_task():
    """Runs the extraction and chunking pipeline."""
    run_pipeline(
        pdf_dir=PDF_DIR,
        csv_path=CSV_PATH,
        jsonl_dir=JSONL_DIR,
        output_dir=SILVER_DIR,          # 🥈 Silver: normalized docs
        peshawar_pdf_dir=PESHAWAR_PDF_DIR,
        peshawar_csv_path=PESHAWAR_CSV_PATH,
        sc_dir=SC_DIR,
        weaviate_url=None,              # Ingest handled by the next task
        archive_dir=ARCHIVE_DIR,
        quarantine_dir=QUARANTINE_DIR,
        chunks_output_dir=GOLD_DIR,     # 🥇 Gold: vector chunks
    )

def run_ingestion_task():
    """Loads chunks from Gold layer to Weaviate Cloud."""
    chunks_file = os.path.join(GOLD_DIR, "processed_chunks.jsonl")
    if not os.path.exists(chunks_file):
        raise FileNotFoundError(f"Gold chunks file not found at {chunks_file}")

    ingest_to_weaviate(
        chunks_file_path=chunks_file,
        weaviate_url=WEAVIATE_URL,
        api_key=WEAVIATE_API_KEY,
    )

with DAG(
    'legal_data_etl_pipeline',
    default_args=default_args,
    description='Orchestrates Legal Preprocessing, Chunking and Ingestion to Weaviate',
    schedule_interval=None,  # Run manually on adding new data
    start_date=datetime(2023, 1, 1),
    catchup=False,
    tags=['legal', 'etl', 'weaviate'],
) as dag:

    # Task 1: Preprocess Bronze raw files → Silver (normalized docs) + Gold (chunks)
    preprocess_data = PythonOperator(
        task_id='preprocess_data',
        python_callable=run_preprocessing_task,
    )

    # Task 2: Load Gold chunks into Weaviate
    load_to_weaviate = PythonOperator(
        task_id='load_to_weaviate',
        python_callable=run_ingestion_task,
    )

    # Task Dependency Flow
    preprocess_data >> load_to_weaviate
