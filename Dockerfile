# Use the official Apache Airflow image as the base
FROM apache/airflow:2.7.2-python3.10

USER root

# Install system dependencies required by PyMuPDF (fitz)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libmupdf-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

USER airflow

# ── Python dependencies ─────────────────────────────────────────────────────
# IMPORTANT: cryptography must be pinned to 41.x
# weaviate-client pulls in cryptography>=42 which ships a Rust-compiled binary
# that uses CPU instructions unavailable in the Docker ARM emulation environment,
# causing a SIGILL (exit 132) crash that prevents Airflow from initialising.
# Pinning to 41.0.4 (the version shipped with the base image) avoids the crash
# while still satisfying all weaviate-client dependency constraints.
RUN pip install --no-cache-dir \
    pymupdf \
    pandas \
    pydantic==2.4.2 \
    weaviate-client \
    cryptography==41.0.4
