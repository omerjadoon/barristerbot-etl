import re
import hashlib
from typing import List, Dict, Any
from preprocessing.schemas import Document, Chunk

class LegalChunker:
    def __init__(self, target_word_size: int = 500, overlap_word_size: int = 100):
        self.target_word_size = target_word_size
        self.overlap_word_size = overlap_word_size

    def count_words(self, text: str) -> int:
        return len(text.split())

    def create_context_header(self, doc_type: str, metadata: Dict[str, Any]) -> str:
        """Creates a text prefix containing crucial document context for the chunk."""
        if doc_type == "judgment":
            title = metadata.get("case_title", "Unknown Case")
            court = metadata.get("court", "High Court")
            case_num = metadata.get("case_number", "")
            judge = metadata.get("author_judge", "")
            date_str = metadata.get("order_date", "")
            
            header = f"[DOCUMENT CONTEXT: COURT CASE]\n"
            header += f"Case Title: {title}\n"
            header += f"Court: {court}\n"
            if case_num:
                header += f"Case Number: {case_num}\n"
            if judge:
                header += f"Author Judge: {judge}\n"
            if date_str:
                header += f"Judgment Date: {date_str}\n"
            header += "\n"
            return header
            
        elif doc_type == "law":
            law_name = metadata.get("law_name", "Statute")
            sec_num = metadata.get("section_number", "")
            sec_title = metadata.get("section_title", "")
            
            header = f"[DOCUMENT CONTEXT: STATUTE]\n"
            header += f"Act/Code: {law_name}\n"
            header += f"Section: {sec_num} ({sec_title})\n"
            header += "\n"
            return header
            
        return ""

    def chunk_judgment(self, doc: Document) -> List[Chunk]:
        """Splits judgments recursively by paragraph to avoid splitting citations/arguments."""
        text = doc.content
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        
        # If there are no clear paragraphs, split by single newline
        if len(paragraphs) < 3:
            paragraphs = [p.strip() for p in text.split("\n") if p.strip()]

        header = self.create_context_header("judgment", doc.metadata)
        header_word_count = self.count_words(header)
        max_chunk_words = self.target_word_size - header_word_count

        chunks = []
        current_paras = []
        current_word_count = 0
        chunk_idx = 0

        for para in paragraphs:
            para_word_count = self.count_words(para)
            
            # If a single paragraph is too large (rare), split it by sentences
            if para_word_count > max_chunk_words:
                sentences = re.split(r'(?<=[.!?])\s+', para)
                for sentence in sentences:
                    sentence_word_count = self.count_words(sentence)
                    if current_word_count + sentence_word_count > max_chunk_words and current_paras:
                        # Flush current chunk
                        chunk_text = header + " ".join(current_paras)
                        chunk_id = hashlib.md5(f"{doc.doc_id}_chunk_{chunk_idx}".encode()).hexdigest()
                        chunks.append(Chunk(
                            chunk_id=chunk_id,
                            doc_id=doc.doc_id,
                            doc_type="judgment",
                            text=chunk_text,
                            chunk_index=chunk_idx,
                            metadata=self.flatten_metadata(doc.metadata, chunk_idx)
                        ))
                        chunk_idx += 1
                        
                        # Retain overlap sentences
                        overlap_paras = []
                        overlap_words = 0
                        for p in reversed(current_paras):
                            p_words = self.count_words(p)
                            if overlap_words + p_words <= self.overlap_word_size:
                                overlap_paras.insert(0, p)
                                overlap_words += p_words
                            else:
                                break
                        current_paras = overlap_paras
                        current_word_count = overlap_words
                    
                    current_paras.append(sentence)
                    current_word_count += sentence_word_count
            else:
                if current_word_count + para_word_count > max_chunk_words and current_paras:
                    # Flush current chunk
                    chunk_text = header + "\n\n".join(current_paras)
                    chunk_id = hashlib.md5(f"{doc.doc_id}_chunk_{chunk_idx}".encode()).hexdigest()
                    chunks.append(Chunk(
                        chunk_id=chunk_id,
                        doc_id=doc.doc_id,
                        doc_type="judgment",
                        text=chunk_text,
                        chunk_index=chunk_idx,
                        metadata=self.flatten_metadata(doc.metadata, chunk_idx)
                    ))
                    chunk_idx += 1
                    
                    # Compute overlap from paragraphs
                    overlap_paras = []
                    overlap_words = 0
                    for p in reversed(current_paras):
                        p_words = self.count_words(p)
                        if overlap_words + p_words <= self.overlap_word_size:
                            overlap_paras.insert(0, p)
                            overlap_words += p_words
                        else:
                            break
                    current_paras = overlap_paras
                    current_word_count = overlap_words
                
                current_paras.append(para)
                current_word_count += para_word_count

        # Flush final chunk
        if current_paras:
            chunk_text = header + "\n\n".join(current_paras)
            chunk_id = hashlib.md5(f"{doc.doc_id}_chunk_{chunk_idx}".encode()).hexdigest()
            chunks.append(Chunk(
                chunk_id=chunk_id,
                doc_id=doc.doc_id,
                doc_type="judgment",
                text=chunk_text,
                chunk_index=chunk_idx,
                metadata=self.flatten_metadata(doc.metadata, chunk_idx)
            ))

        return chunks

    def chunk_law(self, doc: Document) -> List[Chunk]:
        """Keeps statute sections intact unless they exceed limits."""
        text = doc.content
        word_count = self.count_words(text)
        header = self.create_context_header("law", doc.metadata)

        # If it's small, keep as a single unified chunk (ideal for statutory sections)
        if word_count <= (self.target_word_size - self.count_words(header)):
            chunk_id = hashlib.md5(f"{doc.doc_id}_chunk_0".encode()).hexdigest()
            return [Chunk(
                chunk_id=chunk_id,
                doc_id=doc.doc_id,
                doc_type="law",
                text=header + text,
                chunk_index=0,
                metadata=self.flatten_metadata(doc.metadata, 0)
            )]
        
        # Otherwise, split section by subsections/paragraphs
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        chunks = []
        current_paras = []
        current_word_count = 0
        chunk_idx = 0
        max_chunk_words = self.target_word_size - self.count_words(header)

        for para in paragraphs:
            para_word_count = self.count_words(para)
            if current_word_count + para_word_count > max_chunk_words and current_paras:
                chunk_text = header + "\n\n".join(current_paras)
                chunk_id = hashlib.md5(f"{doc.doc_id}_chunk_{chunk_idx}".encode()).hexdigest()
                chunks.append(Chunk(
                    chunk_id=chunk_id,
                    doc_id=doc.doc_id,
                    doc_type="law",
                    text=chunk_text,
                    chunk_index=chunk_idx,
                    metadata=self.flatten_metadata(doc.metadata, chunk_idx)
                ))
                chunk_idx += 1
                current_paras = []
                current_word_count = 0
            
            current_paras.append(para)
            current_word_count += para_word_count

        if current_paras:
            chunk_text = header + "\n\n".join(current_paras)
            chunk_id = hashlib.md5(f"{doc.doc_id}_chunk_{chunk_idx}".encode()).hexdigest()
            chunks.append(Chunk(
                chunk_id=chunk_id,
                doc_id=doc.doc_id,
                doc_type="law",
                text=chunk_text,
                chunk_index=chunk_idx,
                metadata=self.flatten_metadata(doc.metadata, chunk_idx)
            ))

        return chunks

    def flatten_metadata(self, metadata: Dict[str, Any], chunk_index: int) -> Dict[str, Any]:
        """Flattens nested lists/objects to make metadata fully queryable in Weaviate filters."""
        flat = {}
        for k, v in metadata.items():
            if isinstance(v, list):
                if len(v) == 0:
                    flat[k] = []
                elif isinstance(v[0], str):
                    flat[k] = v
                elif hasattr(v[0], "model_dump"):  # Pydantic advocate role list
                    flat[k] = [item.name for item in v]
                elif isinstance(v[0], dict):
                    flat[k] = [item.get("name", "") for item in v]
            else:
                flat[k] = v
        flat["chunk_index"] = chunk_index
        return flat

    def chunk_document(self, doc: Document) -> List[Chunk]:
        if doc.doc_type == "judgment":
            return self.chunk_judgment(doc)
        elif doc.doc_type == "law":
            return self.chunk_law(doc)
        return []
