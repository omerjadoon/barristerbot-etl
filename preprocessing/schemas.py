from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Any

class Advocate(BaseModel):
    name: str
    role: str

class JudgmentMetadata(BaseModel):
    case_id: str
    case_title: str
    case_number: str
    court: str
    author_judge: str
    judgment_type: str  # e.g., Final Judgment, Short Order, Review Application
    order_date: Optional[str] = None
    outcome: str        # e.g., Allowed, Dismissed, Acquitted, Pending
    referenced_laws: List[str] = Field(default_factory=list)
    advocates: List[Advocate] = Field(default_factory=list)
    source_filename: str

class LawMetadata(BaseModel):
    law_id: str         # e.g., CPC, PPC, CrPC
    law_name: str       # e.g., Code of Civil Procedure
    section_number: str # e.g., 249-A
    section_title: str  # e.g., Power of Magistrate to acquit accused at any stage
    source_filename: str

class Document(BaseModel):
    doc_id: str
    doc_type: str       # "judgment" or "law"
    title: str          # Title of section or case title
    content: str        # Clean full text of the section or judgment
    metadata: Dict[str, Any]  # Maps to either JudgmentMetadata or LawMetadata

class Chunk(BaseModel):
    chunk_id: str
    doc_id: str
    doc_type: str       # "judgment" or "law"
    text: str           # The chunk's text
    chunk_index: int    # Sequential index of the chunk
    metadata: Dict[str, Any]  # Flattened metadata for vector search filters
