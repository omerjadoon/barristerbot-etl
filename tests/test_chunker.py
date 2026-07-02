import pytest
from preprocessing.schemas import Document
from preprocessing.chunker import LegalChunker

def test_context_header_judgment():
    chunker = LegalChunker()
    metadata = {
        "case_title": "Kamran vs State",
        "court": "Peshawar High Court",
        "case_number": "W.P 100/2024",
        "author_judge": "Justice Khan",
        "order_date": "2024-05-10"
    }
    header = chunker.create_context_header("judgment", metadata)
    assert "[DOCUMENT CONTEXT: COURT CASE]" in header
    assert "Case Title: Kamran vs State" in header
    assert "Court: Peshawar High Court" in header
    assert "Case Number: W.P 100/2024" in header
    assert "Author Judge: Justice Khan" in header
    assert "Judgment Date: 2024-05-10" in header

def test_context_header_law():
    chunker = LegalChunker()
    metadata = {
        "law_name": "Pakistan Penal Code, 1860",
        "section_number": "302",
        "section_title": "Punishment of Qatl-i-Amd"
    }
    header = chunker.create_context_header("law", metadata)
    assert "[DOCUMENT CONTEXT: STATUTE]" in header
    assert "Act/Code: Pakistan Penal Code, 1860" in header
    assert "Section: 302 (Punishment of Qatl-i-Amd)" in header

def test_flatten_metadata():
    chunker = LegalChunker()
    metadata = {
        "case_title": "Kamran vs State",
        "referenced_laws": ["PPC Section 302", "CrPC Section 561-A"],
        "advocates": [
            {"name": "Zubair", "role": "petitioner"},
            {"name": "Ali", "role": "respondent"}
        ]
    }
    flat = chunker.flatten_metadata(metadata, chunk_index=2)
    assert flat["case_title"] == "Kamran vs State"
    assert flat["referenced_laws"] == ["PPC Section 302", "CrPC Section 561-A"]
    # Verify we flatten advocates to lists of names
    assert flat["advocates"] == ["Zubair", "Ali"]
    assert flat["chunk_index"] == 2

def test_chunk_law_small():
    chunker = LegalChunker(target_word_size=100, overlap_word_size=20)
    doc = Document(
        doc_id="law_123",
        doc_type="law",
        title="PPC Section 302",
        content="Whoever commits qatl-i-amd shall be punished with death or imprisonment for life.",
        metadata={
            "law_name": "Pakistan Penal Code",
            "section_number": "302",
            "section_title": "Punishment"
        }
    )
    chunks = chunker.chunk_document(doc)
    assert len(chunks) == 1
    assert chunks[0].doc_type == "law"
    assert chunks[0].chunk_index == 0
    assert "Whoever commits qatl-i-amd" in chunks[0].text

def test_chunk_judgment_by_paragraph():
    chunker = LegalChunker(target_word_size=150, overlap_word_size=30)
    # Target size is 150 words. Let's make paragraphs.
    para1 = "This is paragraph one. It talks about the facts of the case in detail. " * 5 # ~50 words
    para2 = "This is paragraph two. It outlines the arguments presented by the petitioner's counsel. " * 5 # ~60 words
    para3 = "This is paragraph three. The judge considers the precedent set by the supreme court. " * 5 # ~65 words
    
    doc = Document(
        doc_id="judgment_123",
        doc_type="judgment",
        title="Test Judgment",
        content=f"{para1}\n\n{para2}\n\n{para3}",
        metadata={
            "case_title": "Test Judgment",
            "court": "Supreme Court of Pakistan"
        }
    )
    chunks = chunker.chunk_document(doc)
    assert len(chunks) >= 2
    for chunk in chunks:
        assert "[DOCUMENT CONTEXT: COURT CASE]" in chunk.text
        assert chunk.doc_type == "judgment"
