import pytest
from preprocessing.schemas import Document, Chunk, JudgmentMetadata, LawMetadata, Advocate

def test_advocate_validation():
    advocate = Advocate(name="Mr. Aslam", role="petitioner")
    assert advocate.name == "Mr. Aslam"
    assert advocate.role == "petitioner"

def test_judgment_metadata_validation():
    meta = JudgmentMetadata(
        case_id="123",
        case_title="State vs John",
        case_number="C.A. 12/2025",
        court="Supreme Court of Pakistan",
        author_judge="Justice Shah",
        judgment_type="Final Judgment",
        order_date="2025-01-01",
        outcome="Allowed",
        referenced_laws=["PPC Section 302"],
        advocates=[Advocate(name="Ahmad", role="respondent")],
        source_filename="test.pdf"
    )
    assert meta.case_title == "State vs John"
    assert len(meta.advocates) == 1
    assert meta.advocates[0].name == "Ahmad"

def test_document_validation():
    doc = Document(
        doc_id="doc_xyz",
        doc_type="judgment",
        title="State vs John",
        content="This is the full text of the case.",
        metadata={
            "case_id": "123",
            "case_title": "State vs John",
            "case_number": "C.A. 12/2025",
            "court": "Supreme Court of Pakistan",
            "author_judge": "Justice Shah",
            "judgment_type": "Final Judgment",
            "order_date": "2025-01-01",
            "outcome": "Allowed",
            "referenced_laws": ["PPC Section 302"],
            "advocates": [{"name": "Ahmad", "role": "respondent"}],
            "source_filename": "test.pdf"
        }
    )
    assert doc.doc_id == "doc_xyz"
    assert doc.metadata["outcome"] == "Allowed"
