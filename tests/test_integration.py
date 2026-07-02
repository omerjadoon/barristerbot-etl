import os
import json
import shutil
import tempfile
import pytest
import pandas as pd
import fitz  # PyMuPDF
from preprocessing.pipeline import run_pipeline

@pytest.fixture
def temp_pipeline_env():
    # Setup temporary directory structure
    tmp_dir = tempfile.mkdtemp()
    
    # Create subfolders matching medallion/pipeline structure
    pdf_dir = os.path.join(tmp_dir, "raw", "bhc")
    peshawar_pdf_dir = os.path.join(tmp_dir, "raw", "phc")
    sc_dir = os.path.join(tmp_dir, "raw", "sc")
    jsonl_dir = os.path.join(tmp_dir, "raw", "legal_codes")
    
    archive_dir = os.path.join(tmp_dir, "archive")
    quarantine_dir = os.path.join(tmp_dir, "quarantine")
    output_dir = os.path.join(tmp_dir, "silver")
    chunks_output_dir = os.path.join(tmp_dir, "gold")
    
    os.makedirs(pdf_dir)
    os.makedirs(peshawar_pdf_dir)
    os.makedirs(sc_dir)
    os.makedirs(jsonl_dir)
    os.makedirs(archive_dir)
    os.makedirs(quarantine_dir)
    os.makedirs(output_dir)
    os.makedirs(chunks_output_dir)
    
    # Helper to generate a valid PDF with some text
    def create_dummy_pdf(path, text):
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((50, 50), text)
        doc.save(path)
        doc.close()
        # Pad the file to be > 1024 bytes so it's not quarantined as a stub
        with open(path, "ab") as f:
            f.write(b" " * 2048)

    # 1. Create BHC dummy PDF and CSV
    bhc_pdf_path = os.path.join(pdf_dir, "bhc_case_1.pdf")
    create_dummy_pdf(
        bhc_pdf_path,
        "Balochistan High Court Judgment.\nMr. Jameel Ahmed, Advocate for the petitioner.\n"
        "Under Section 302 of the PPC. The appeal is allowed and the accused is acquitted."
    )
    bhc_csv_path = os.path.join(pdf_dir, "metadata.csv")
    bhc_df = pd.DataFrame([{
        "CASE_ID": 1001,
        "CASE_TITLE": "State Vs Jameel",
        "REGISTER_NUMBER": "C.A. 101/2023",
        "AUTHOR_JUDGE": "Justice Mandokhail",
        "TYPE_NAME": "Judgment",
        "ORDER_DATE": "2023-08-15",
        "status": "success",
        "filename": "bhc_case_1.pdf"
    }])
    bhc_df.to_csv(bhc_csv_path, index=False)

    # 2. Create PHC dummy PDF and CSV
    phc_pdf_path = os.path.join(peshawar_pdf_dir, "phc_case_1.pdf")
    create_dummy_pdf(
        phc_pdf_path,
        "Peshawar High Court.\nBefore JUSTICE KHAN.\nMr. Tariq Khan, Advocate for the respondent.\n"
        "Section 249-A of the CrPC. The petition is dismissed."
    )
    phc_csv_path = os.path.join(peshawar_pdf_dir, "metadata.csv")
    phc_df = pd.DataFrame([{
        "row_num": 501,
        "title": "W.P No. 99-P of 2024 Kamran Vs State",
        "date": "2024-03-20",
        "status": "success",
        "filename": "phc_case_1.pdf"
    }])
    phc_df.to_csv(phc_csv_path, index=False)

    # 3. Create SC dummy PDF under Judge folder
    sc_judge_dir = os.path.join(sc_dir, "Justice_Bandial")
    os.makedirs(sc_judge_dir)
    sc_pdf_path = os.path.join(sc_judge_dir, "const.p._12_2022.pdf")
    create_dummy_pdf(
        sc_pdf_path,
        "Supreme Court of Pakistan.\nConstitution Petition No. 12 of 2022.\n"
        "Muhammad Ali Versus Federation of Pakistan.\n"
        "Mr. Raza Farooq, Advocate for petitioner.\n"
        "Article 184 of the Constitution. Decided on: 12-05-2022. Order accordingly."
    )

    # 4. Create Laws dummy JSONL
    law_jsonl_path = os.path.join(jsonl_dir, "ppc.jsonl")
    with open(law_jsonl_path, "w", encoding="utf-8") as f:
        f.write(json.dumps({
            "id": "section_302",
            "text": "302. Punishment of Qatl-i-Amd. Whoever commits qatl-i-amd shall be punished with death."
        }) + "\n")

    yield {
        "pdf_dir": pdf_dir,
        "csv_path": bhc_csv_path,
        "peshawar_pdf_dir": peshawar_pdf_dir,
        "peshawar_csv_path": phc_csv_path,
        "sc_dir": sc_dir,
        "jsonl_dir": jsonl_dir,
        "archive_dir": archive_dir,
        "quarantine_dir": quarantine_dir,
        "output_dir": output_dir,
        "chunks_output_dir": chunks_output_dir,
        "tmp_dir": tmp_dir
    }

    # Teardown
    shutil.rmtree(tmp_dir)

def test_pipeline_integration(temp_pipeline_env):
    env = temp_pipeline_env
    
    # Run the full pipeline
    run_pipeline(
        pdf_dir=env["pdf_dir"],
        csv_path=env["csv_path"],
        peshawar_pdf_dir=env["peshawar_pdf_dir"],
        peshawar_csv_path=env["peshawar_csv_path"],
        sc_dir=env["sc_dir"],
        jsonl_dir=env["jsonl_dir"],
        archive_dir=env["archive_dir"],
        quarantine_dir=env["quarantine_dir"],
        output_dir=env["output_dir"],
        chunks_output_dir=env["chunks_output_dir"]
    )
    
    # Check outputs exist
    docs_file = os.path.join(env["output_dir"], "processed_documents.jsonl")
    chunks_file = os.path.join(env["chunks_output_dir"], "processed_chunks.jsonl")
    
    assert os.path.exists(docs_file)
    assert os.path.exists(chunks_file)
    
    # Read processed documents (Silver stage)
    docs = []
    with open(docs_file, "r") as f:
        for line in f:
            docs.append(json.loads(line))
            
    # We expect 4 documents:
    # 1. Law (PPC Section 302)
    # 2. BHC Case 1001
    # 3. PHC Case 501
    # 4. SC Case
    assert len(docs) == 4
    
    doc_types = [d["doc_type"] for d in docs]
    assert "law" in doc_types
    assert "judgment" in doc_types
    
    # Verify BHC doc values
    bhc_doc = next(d for d in docs if d["metadata"].get("court") == "Balochistan High Court")
    assert bhc_doc["title"] == "State Vs Jameel"
    assert bhc_doc["metadata"]["outcome"] == "Allowed" # allowed prioritized over acquitted
    assert "PPC Section 302" in bhc_doc["metadata"]["referenced_laws"]
    assert len(bhc_doc["metadata"]["advocates"]) == 1
    assert bhc_doc["metadata"]["advocates"][0]["name"] == "Jameel Ahmed"
    
    # Verify PHC doc values
    phc_doc = next(d for d in docs if d["metadata"].get("court") == "Peshawar High Court")
    assert phc_doc["metadata"]["outcome"] == "Dismissed"
    assert "CrPC Section 249-A" in phc_doc["metadata"]["referenced_laws"]
    
    # Verify SC doc values
    sc_doc = next(d for d in docs if d["metadata"].get("court") == "Supreme Court of Pakistan")
    assert sc_doc["metadata"]["author_judge"] == "Justice_Bandial"
    # Matches the actual output where Article prefix translates to 'Section' in extractor
    assert "Constitution Section 184" in sc_doc["metadata"]["referenced_laws"]

    # Verify Gold chunks exist
    chunks = []
    with open(chunks_file, "r") as f:
        for line in f:
            chunks.append(json.loads(line))
            
    assert len(chunks) >= 4
    for chunk in chunks:
        assert "chunk_id" in chunk
        assert "text" in chunk
        assert "metadata" in chunk
        
    # Verify archiving moved the files
    assert not os.path.exists(os.path.join(env["pdf_dir"], "bhc_case_1.pdf"))
    assert not os.path.exists(os.path.join(env["peshawar_pdf_dir"], "phc_case_1.pdf"))
    assert not os.path.exists(os.path.join(env["sc_dir"], "Justice_Bandial", "const.p._12_2022.pdf"))
    assert not os.path.exists(os.path.join(env["jsonl_dir"], "ppc.jsonl"))
    
    # Verify archive directory structure has them
    assert os.path.exists(os.path.join(env["archive_dir"], "bhc", "bhc_case_1.pdf"))
    assert os.path.exists(os.path.join(env["archive_dir"], "phc", "phc_case_1.pdf"))
    assert os.path.exists(os.path.join(env["archive_dir"], "sc", "Justice_Bandial", "const.p._12_2022.pdf"))
    assert os.path.exists(os.path.join(env["archive_dir"], "legal_codes", "ppc.jsonl"))
