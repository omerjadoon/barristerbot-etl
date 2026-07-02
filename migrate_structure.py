"""
migrate_structure.py
Reorganizes the legal dataset workspace into a production-grade Medallion structure:
- bronze/raw/ : original PDFs and raw CSVs
- bronze/archive/ : parsed files
- bronze/quarantine/ : stubs and errors
- silver/ : cleansed/normalized processed_documents.jsonl
- gold/ : vectorized processed_chunks.jsonl
Safe to run multiple times (idempotent).
"""
import os
import shutil
from pathlib import Path

BASE = Path("/Users/omerkhanjadoon/Documents/legal dataset")

# ── Define new directory layout ──────────────────────────────────────────────
DIRS = [
    "data_warehouse/bronze/raw/bhc",
    "data_warehouse/bronze/raw/phc",
    "data_warehouse/bronze/raw/legal_codes",
    "data_warehouse/bronze/raw/sc",
    "data_warehouse/bronze/archive",
    "data_warehouse/bronze/quarantine/stubs",
    "data_warehouse/bronze/quarantine/parse_errors",
    "data_warehouse/silver",
    "data_warehouse/gold",
]

def create_dirs():
    for d in DIRS:
        (BASE / d).mkdir(parents=True, exist_ok=True)
    print("✓ Medallion directory structure created")

# ── Move helpers ──────────────────────────────────────────────────────────────
def move_file(src: Path, dst: Path):
    if not src.exists():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not dst.exists():
        shutil.move(str(src), str(dst))
        return True
    return False  # already at destination

def move_dir_contents(src_dir: Path, dst_dir: Path, extensions=None):
    if not src_dir.is_dir():
        return 0
    moved = 0
    for f in src_dir.iterdir():
        if f.is_file():
            if extensions is None or f.suffix.lower() in extensions:
                if move_file(f, dst_dir / f.name):
                    moved += 1
    return moved

# ── Transitional Helper ───────────────────────────────────────────────────────
def transition_old_warehouse():
    """Shifts existing data_warehouse folders to the new bronze/silver/gold structure."""
    print("\n=== Transitioning existing folders to Medallion stages ===")
    
    # 1. raw -> bronze/raw
    old_raw = BASE / "data_warehouse/raw"
    new_raw = BASE / "data_warehouse/bronze/raw"
    if old_raw.is_dir() and not new_raw.is_dir():
        shutil.move(str(old_raw), str(new_raw))
        print("✓ Moved data_warehouse/raw/ → data_warehouse/bronze/raw/")
    elif old_raw.is_dir() and new_raw.is_dir():
        # Merge if both exist
        for item in old_raw.iterdir():
            target = new_raw / item.name
            if not target.exists():
                shutil.move(str(item), str(target))
        shutil.rmtree(str(old_raw))
        print("✓ Merged and cleaned old raw/ into bronze/raw/")

    # 2. archive -> bronze/archive
    old_archive = BASE / "data_warehouse/archive"
    new_archive = BASE / "data_warehouse/bronze/archive"
    if old_archive.is_dir() and not new_archive.is_dir():
        shutil.move(str(old_archive), str(new_archive))
        print("✓ Moved data_warehouse/archive/ → data_warehouse/bronze/archive/")
    elif old_archive.is_dir() and new_archive.is_dir():
        for item in old_archive.iterdir():
            target = new_archive / item.name
            if not target.exists():
                shutil.move(str(item), str(target))
        shutil.rmtree(str(old_archive))
        print("✓ Merged and cleaned old archive/ into bronze/archive/")

    # 3. quarantine -> bronze/quarantine
    old_quarantine = BASE / "data_warehouse/quarantine"
    new_quarantine = BASE / "data_warehouse/bronze/quarantine"
    if old_quarantine.is_dir() and not new_quarantine.is_dir():
        shutil.move(str(old_quarantine), str(new_quarantine))
        print("✓ Moved data_warehouse/quarantine/ → data_warehouse/bronze/quarantine/")
    elif old_quarantine.is_dir() and new_quarantine.is_dir():
        for item in old_quarantine.iterdir():
            target = new_quarantine / item.name
            if not target.exists():
                shutil.move(str(item), str(target))
        shutil.rmtree(str(old_quarantine))
        print("✓ Merged and cleaned old quarantine/ into bronze/quarantine/")

    # 4. processed/*.jsonl -> silver/ and gold/
    old_processed_docs = BASE / "processed/processed_documents.jsonl"
    new_processed_docs = BASE / "data_warehouse/silver/processed_documents.jsonl"
    if old_processed_docs.exists() and not new_processed_docs.exists():
        shutil.move(str(old_processed_docs), str(new_processed_docs))
        print("✓ Moved processed_documents.jsonl → data_warehouse/silver/")

    old_processed_chunks = BASE / "processed/processed_chunks.jsonl"
    new_processed_chunks = BASE / "data_warehouse/gold/processed_chunks.jsonl"
    if old_processed_chunks.exists() and not new_processed_chunks.exists():
        shutil.move(str(old_processed_chunks), str(new_processed_chunks))
        print("✓ Moved processed_chunks.jsonl → data_warehouse/gold/")

    # Remove root level processed folder if empty
    old_processed_dir = BASE / "processed"
    if old_processed_dir.is_dir() and not list(old_processed_dir.iterdir()):
        old_processed_dir.rmdir()
        print("✓ Removed empty root processed/ directory")

# ── Migration steps ───────────────────────────────────────────────────────────
def migrate_bhc():
    src = BASE / "downloads_bhc"
    dst = BASE / "data_warehouse/bronze/raw/bhc"

    n = move_dir_contents(src, dst, extensions=[".pdf"])
    if n:
        print(f"✓ BHC PDFs: moved {n} files  →  bronze/raw/bhc/")

    meta_src = BASE / "metadata_bhc.csv"
    meta_dst = BASE / "data_warehouse/bronze/raw/bhc/metadata.csv"
    if move_file(meta_src, meta_dst):
        print("✓ BHC metadata: metadata_bhc.csv → bronze/raw/bhc/metadata.csv")


def migrate_phc():
    src = BASE / "all_data/peshawardata"
    dst = BASE / "data_warehouse/bronze/raw/phc"

    n = move_dir_contents(src, dst, extensions=[".pdf"])
    if n:
        print(f"✓ PHC PDFs: moved {n} files  →  bronze/raw/phc/")

    for meta_name in ["metadata_peshawar.csv", "metadata.csv"]:
        meta_src = src / meta_name
        meta_dst = dst / "metadata.csv"
        if meta_src.exists() and not meta_dst.exists():
            shutil.move(str(meta_src), str(meta_dst))
            print(f"✓ PHC metadata: {meta_name} → bronze/raw/phc/metadata.csv")
            break


def migrate_legal_codes():
    src = BASE / "all_data/legal codes"
    dst = BASE / "data_warehouse/bronze/raw/legal_codes"

    n = move_dir_contents(src, dst, extensions=[".jsonl"])
    if n:
        print(f"✓ Legal codes: moved {n} JSONL files  →  bronze/raw/legal_codes/")


def migrate_sc():
    src = BASE / "all_data/Supreme Court Judgements"
    dst = BASE / "data_warehouse/bronze/raw/sc"
    if not src.is_dir():
        return

    moved_folders = 0
    for item in src.iterdir():
        if item.is_dir():
            target = dst / item.name
            if not target.exists():
                shutil.move(str(item), str(target))
                moved_folders += 1
    if moved_folders:
        print(f"✓ Supreme Court Judgements: moved {moved_folders} judge folders → bronze/raw/sc/")


def remove_empty_dirs():
    """Clean up empty legacy directories after migration."""
    candidates = [
        BASE / "downloads_bhc",
        BASE / "all_data/peshawardata",
        BASE / "all_data/legal codes",
        BASE / "all_data/Supreme Court Judgements",
        BASE / "all_data",
    ]
    for d in candidates:
        if d.is_dir():
            remaining = [f for f in d.rglob("*") if f.is_file()]
            if not remaining:
                shutil.rmtree(str(d))
                print(f"✓ Removed empty dir: {d.relative_to(BASE)}")


def print_summary():
    print("\n── Final Medallion Warehouse structure ─────────────────────")
    for d in sorted((BASE / "data_warehouse").rglob("*")):
        if d.is_dir():
            count = len(list(d.glob("*.pdf"))) + len(list(d.glob("*.jsonl"))) + len(list(d.glob("*.csv")))
            # For sc subfolders, do recursive count
            if "sc" in d.parts or d.name == "sc":
                count = len(list(d.rglob("*.pdf")))
            
            label = f"  ({count} files)" if count else ""
            indent = "  " * (len(d.relative_to(BASE).parts) - 1)
            print(f"{indent}{d.name}/{label}")


if __name__ == "__main__":
    print("=== Legal Dataset Medallion Structure Migration ===\n")
    create_dirs()
    transition_old_warehouse()
    print()
    migrate_bhc()
    migrate_phc()
    migrate_legal_codes()
    migrate_sc()
    print()
    remove_empty_dirs()
    print_summary()
    print("\n✓ Medallion migration complete.")
