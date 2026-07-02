import os
import re
import json
import hashlib
import shutil
import pandas as pd
import fitz  # PyMuPDF
from typing import List, Dict, Any, Generator
from preprocessing.schemas import Document, JudgmentMetadata, LawMetadata, Advocate

class LegalExtractor:
    def __init__(self, 
                 pdf_dir: str = None, 
                 csv_path: str = None, 
                 jsonl_dir: str = None,
                 peshawar_pdf_dir: str = None,
                 peshawar_csv_path: str = None,
                 sc_dir: str = None,
                 archive_dir: str = None,
                 quarantine_dir: str = None):
        self.pdf_dir = pdf_dir
        self.csv_path = csv_path
        self.jsonl_dir = jsonl_dir
        self.peshawar_pdf_dir = peshawar_pdf_dir
        self.peshawar_csv_path = peshawar_csv_path
        self.sc_dir = sc_dir
        self.archive_dir = archive_dir
        self.quarantine_dir = quarantine_dir
        
        # Mapping from code IDs to full names
        self.law_names_map = {
            "CPC": "Code of Civil Procedure, 1908",
            "CRPC": "Code of Criminal Procedure, 1898",
            "PPC": "Pakistan Penal Code, 1860",
            "QANOON-E-SHAHADAT": "Qanoon-e-Shahadat Order, 1984"
        }

    def clean_text(self, text: str) -> str:
        """Removes standard watermark phrases and simplifies whitespaces."""
        watermarks = [
            r"Only for viewing purpose\.\s*Contact office for certified copy\.",
            r"Page\s+\d+\s+of\s+\d+",
            r"Page\s+\d+",
            r"CC-\d+",
            r"JUDGMENT SHEET",
            r"PESHAWAR HIGH COURT"
        ]
        cleaned = text
        for watermark in watermarks:
            cleaned = re.sub(watermark, "", cleaned, flags=re.IGNORECASE)
        
        cleaned = re.sub(r'[ \t]+', ' ', cleaned)
        cleaned = re.sub(r'\n\s*\n+', '\n\n', cleaned)
        return cleaned.strip()

    def extract_heuristics(self, text: str) -> Dict[str, Any]:
        """Applies heuristic rules to extract advocates, laws referenced, and outcome."""
        metadata = {}
        
        # 1. Referenced Laws (e.g. Section 249-A Cr.P.C, Section 302 PPC, Article 199)
        law_pattern = r"(?:Section|Sec\.|Article|Art\.)\s*(\d+(?:-[A-Z])?)\s*(?:of\s+the\s+|of\s+)?(Cr\.?P\.?C|C\.?P\.?C|P\.?P\.?C|Constitution|Q\.?S\.?O|Pakistan\s+Penal\s+Code|Code\s+of\s+Civil\s+Procedure|Code\s+of\s+Criminal\s+Procedure)"
        matches = re.findall(law_pattern, text, re.IGNORECASE)
        
        referenced_laws = []
        for section, law in matches:
            law_std = law.upper().replace(".", "")
            if "CRPC" in law_std or "CRIMINAL" in law_std:
                law_name = "CrPC"
            elif "CPC" in law_std or "CIVIL" in law_std:
                law_name = "CPC"
            elif "PPC" in law_std or "PENAL" in law_std:
                law_name = "PPC"
            elif "CONSTITUTION" in law_std:
                law_name = "Constitution"
            elif "QSO" in law_std:
                law_name = "QSO"
            else:
                law_name = law
            referenced_laws.append(f"{law_name} Section {section}")
        
        metadata["referenced_laws"] = sorted(list(set(referenced_laws)))
        
        # 2. Advocates (e.g., Mr. X, Advocate for the petitioner)
        advocate_pattern = r"(?:Mr\.|Ms\.|Mrs\.|M/s)\s*([^,]+),\s*Advocate\s*(?:for\s+the\s+|for\s+)?([^.\n=]+)"
        adv_matches = re.findall(advocate_pattern, text, re.IGNORECASE)
        
        advocates = []
        seen_advs = set()
        for name, role in adv_matches:
            name_clean = name.strip()
            role_clean = role.strip()
            if name_clean not in seen_advs and len(name_clean) > 3:
                seen_advs.add(name_clean)
                advocates.append(Advocate(name=name_clean, role=role_clean))
        metadata["advocates"] = advocates
        
        # 3. Outcome
        verdict = "Pending/Unknown"
        lower_text = text.lower()
        if "dismissed as withdrawn" in lower_text:
            verdict = "Dismissed as Withdrawn"
        elif "dismissed" in lower_text:
            verdict = "Dismissed"
        elif "allowed" in lower_text:
            verdict = "Allowed"
        elif "accepted" in lower_text:
            verdict = "Accepted"
        elif "bail is granted" in lower_text or "ad-interim bail" in lower_text:
            verdict = "Bail Granted"
        elif "bail is refused" in lower_text:
            verdict = "Bail Refused"
        elif "acquitted" in lower_text:
            verdict = "Acquitted"
            
        metadata["outcome"] = verdict
        return metadata

    def parse_judgments(self) -> Generator[Document, None, None]:
        """Loads BHC judgments from CSV metadata, parses corresponding PDFs, and moves files to archive/quarantine."""
        if not self.csv_path or not self.pdf_dir:
            return

        if not os.path.exists(self.csv_path):
            print(f"BHC CSV metadata file not found at {self.csv_path}")
            return

        df = pd.read_csv(self.csv_path)
        success_rows = df[df["status"] == "success"]

        archive_bhc = os.path.join(self.archive_dir, "bhc") if self.archive_dir else None
        stubs_bhc = os.path.join(self.quarantine_dir, "stubs", "bhc") if self.quarantine_dir else None
        errors_bhc = os.path.join(self.quarantine_dir, "parse_errors", "bhc") if self.quarantine_dir else None

        for _, row in success_rows.iterrows():
            csv_filename = row["filename"]
            pdf_filename = csv_filename.rsplit('.', 1)[0] + '.pdf'
            pdf_path = os.path.join(self.pdf_dir, pdf_filename)

            if not os.path.exists(pdf_path):
                continue

            # Skip stub/placeholder files from failed downloads (< 1KB)
            if os.path.getsize(pdf_path) < 1024:
                if stubs_bhc:
                    os.makedirs(stubs_bhc, exist_ok=True)
                    shutil.move(pdf_path, os.path.join(stubs_bhc, pdf_filename))
                    print(f"  [Quarantine] Moved BHC stub file {pdf_filename} to {stubs_bhc}")
                continue

            try:
                doc = fitz.open(pdf_path)
                full_text = ""
                for page in doc:
                    full_text += page.get_text() + "\n"
                
                clean_txt = self.clean_text(full_text)
                heuristics = self.extract_heuristics(clean_txt)

                meta = JudgmentMetadata(
                    case_id=str(row["CASE_ID"]),
                    case_title=str(row["CASE_TITLE"]),
                    case_number=str(row["REGISTER_NUMBER"]),
                    court="Balochistan High Court",
                    author_judge=str(row.get("AUTHOR_JUDGE", "Unknown")),
                    judgment_type=str(row.get("TYPE_NAME", "Order")),
                    order_date=str(row.get("ORDER_DATE")),
                    outcome=heuristics["outcome"],
                    referenced_laws=heuristics["referenced_laws"],
                    advocates=heuristics["advocates"],
                    source_filename=pdf_filename
                )

                doc_id = hashlib.md5(f"bhc_{row['CASE_ID']}".encode()).hexdigest()

                yield Document(
                    doc_id=doc_id,
                    doc_type="judgment",
                    title=meta.case_title,
                    content=clean_txt,
                    metadata=meta.model_dump()
                )

                # Move to archive upon successful processing (control returns here after yield)
                if archive_bhc:
                    os.makedirs(archive_bhc, exist_ok=True)
                    shutil.move(pdf_path, os.path.join(archive_bhc, pdf_filename))
                    print(f"  [Archive] Moved processed BHC PDF {pdf_filename} to {archive_bhc}")

            except Exception as e:
                print(f"Error parsing BHC PDF {pdf_filename}: {e}")
                if errors_bhc:
                    os.makedirs(errors_bhc, exist_ok=True)
                    shutil.move(pdf_path, os.path.join(errors_bhc, pdf_filename))
                    print(f"  [Quarantine] Moved faulty BHC PDF {pdf_filename} to {errors_bhc}")

    def parse_peshawar_judgments(self) -> Generator[Document, None, None]:
        """Loads Peshawar judgments from CSV metadata, parses PDFs, and moves files to archive/quarantine."""
        if not self.peshawar_csv_path or not self.peshawar_pdf_dir:
            return

        if not os.path.exists(self.peshawar_csv_path):
            print(f"Peshawar CSV metadata file not found at {self.peshawar_csv_path}")
            return

        df = pd.read_csv(self.peshawar_csv_path)
        success_rows = df[df["status"] == "success"]

        archive_phc = os.path.join(self.archive_dir, "phc") if self.archive_dir else None
        stubs_phc = os.path.join(self.quarantine_dir, "stubs", "phc") if self.quarantine_dir else None
        errors_phc = os.path.join(self.quarantine_dir, "parse_errors", "phc") if self.quarantine_dir else None

        for _, row in success_rows.iterrows():
            pdf_filename = row["filename"]
            pdf_path = os.path.join(self.peshawar_pdf_dir, pdf_filename)

            if not os.path.exists(pdf_path):
                continue

            # Skip stub/placeholder files from failed downloads (< 1KB)
            if os.path.getsize(pdf_path) < 1024:
                if stubs_phc:
                    os.makedirs(stubs_phc, exist_ok=True)
                    shutil.move(pdf_path, os.path.join(stubs_phc, pdf_filename))
                    print(f"  [Quarantine] Moved PHC stub file {pdf_filename} to {stubs_phc}")
                continue

            try:
                doc = fitz.open(pdf_path)
                full_text = ""
                for page in doc:
                    full_text += page.get_text() + "\n"
                
                clean_txt = self.clean_text(full_text)
                heuristics = self.extract_heuristics(clean_txt)

                # Parse case title and number from the row title
                raw_title = str(row["title"])
                case_num_match = re.match(r"^([^\d]*No\.\s*[\d\w\-]+(?:\s*-\w)?\s*of\s*\d{4})\s*(.*)$", raw_title, re.IGNORECASE)
                if case_num_match:
                    case_number = case_num_match.group(1).strip()
                    case_title = case_num_match.group(2).strip()
                else:
                    case_number = raw_title.split(" Vs ")[0].strip() if " Vs " in raw_title else raw_title
                    case_title = raw_title

                # Heuristic: Extract judge from the Peshawar High Court text
                judge_match = re.search(r"([A-Z\s]{4,30}),\s*(?:J\.|JUDGE)", clean_txt)
                author_judge = judge_match.group(1).strip() if judge_match else "Unknown Judge"

                # Standardize case type based on title prefix
                case_type = "Judgment"
                if "BA" in case_number:
                    case_type = "Bail Application"
                elif "W.P" in case_number or "WP" in case_number:
                    case_type = "Writ Petition"
                elif "Cr.A" in case_number or "Criminal Appeal" in case_number:
                    case_type = "Criminal Appeal"

                meta = JudgmentMetadata(
                    case_id=str(row["row_num"]),
                    case_title=case_title,
                    case_number=case_number,
                    court="Peshawar High Court",
                    author_judge=author_judge,
                    judgment_type=case_type,
                    order_date=str(row.get("date")),
                    outcome=heuristics["outcome"],
                    referenced_laws=heuristics["referenced_laws"],
                    advocates=heuristics["advocates"],
                    source_filename=pdf_filename
                )

                doc_id = hashlib.md5(f"phc_{row['row_num']}".encode()).hexdigest()

                yield Document(
                    doc_id=doc_id,
                    doc_type="judgment",
                    title=meta.case_title,
                    content=clean_txt,
                    metadata=meta.model_dump()
                )

                # Move to archive upon successful processing
                if archive_phc:
                    os.makedirs(archive_phc, exist_ok=True)
                    shutil.move(pdf_path, os.path.join(archive_phc, pdf_filename))
                    print(f"  [Archive] Moved processed PHC PDF {pdf_filename} to {archive_phc}")

            except Exception as e:
                print(f"Error parsing Peshawar PDF {pdf_filename}: {e}")
                if errors_phc:
                    os.makedirs(errors_phc, exist_ok=True)
                    shutil.move(pdf_path, os.path.join(errors_phc, pdf_filename))
                    print(f"  [Quarantine] Moved faulty PHC PDF {pdf_filename} to {errors_phc}")

    def parse_laws(self) -> Generator[Document, None, None]:
        """Loads and parses structured legal codes in JSONL format, archiving files afterward."""
        if not self.jsonl_dir or not os.path.exists(self.jsonl_dir):
            return

        archive_laws = os.path.join(self.archive_dir, "legal_codes") if self.archive_dir else None
        errors_laws = os.path.join(self.quarantine_dir, "parse_errors", "legal_codes") if self.quarantine_dir else None

        for filename in os.listdir(self.jsonl_dir):
            if not filename.endswith(".jsonl"):
                continue

            file_path = os.path.join(self.jsonl_dir, filename)
            law_id = filename.split(".")[0].upper()
            law_name = self.law_names_map.get(law_id, f"{law_id} Act")

            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    for line_num, line in enumerate(f, 1):
                        if not line.strip():
                            continue
                        
                        data = json.loads(line)
                        sec_id = data.get("id", f"section_{line_num}")
                        sec_text = data.get("text", "")

                        sec_num_match = re.search(r"section_([\d\w\-]+)", sec_id, re.IGNORECASE)
                        sec_number = sec_num_match.group(1).replace("_", "-").upper() if sec_num_match else sec_id

                        title_match = re.match(r"^([^\.\n]{5,100})\.", sec_text)
                        sec_title = title_match.group(1).strip() if title_match else f"Section {sec_number}"

                        meta = LawMetadata(
                            law_id=law_id,
                            law_name=law_name,
                            section_number=sec_number,
                            section_title=sec_title,
                            source_filename=filename
                        )

                        doc_id = hashlib.md5(f"law_{law_id}_{sec_number}".encode()).hexdigest()

                        yield Document(
                            doc_id=doc_id,
                            doc_type="law",
                            title=f"{law_id} - Section {sec_number}: {sec_title}",
                            content=sec_text,
                            metadata=meta.model_dump()
                        )

                # Move to archive upon successfully reading all lines
                if archive_laws:
                    os.makedirs(archive_laws, exist_ok=True)
                    shutil.move(file_path, os.path.join(archive_laws, filename))
                    print(f"  [Archive] Moved processed Law JSONL {filename} to {archive_laws}")

            except Exception as e:
                print(f"Error parsing law code {filename}: {e}")
                if errors_laws:
                    os.makedirs(errors_laws, exist_ok=True)
                    shutil.move(file_path, os.path.join(errors_laws, filename))
                    print(f"  [Quarantine] Moved faulty Law JSONL {filename} to {errors_laws}")

    def parse_sc_judgments(self) -> Generator[Document, None, None]:
        """Iterates through Supreme Court judgment folders, parses PDFs, and handles file movement to archive/quarantine."""
        if not self.sc_dir or not os.path.exists(self.sc_dir):
            return

        archive_sc = os.path.join(self.archive_dir, "sc") if self.archive_dir else None
        stubs_sc = os.path.join(self.quarantine_dir, "stubs", "sc") if self.quarantine_dir else None
        errors_sc = os.path.join(self.quarantine_dir, "parse_errors", "sc") if self.quarantine_dir else None

        # Supreme Court files are organized in directories by judge
        for judge_name in sorted(os.listdir(self.sc_dir)):
            judge_path = os.path.join(self.sc_dir, judge_name)
            if not os.path.isdir(judge_path) or judge_name.startswith("."):
                continue

            for pdf_filename in sorted(os.listdir(judge_path)):
                if not pdf_filename.endswith(".pdf"):
                    continue

                pdf_path = os.path.join(judge_path, pdf_filename)
                
                # Skip stub/placeholder files from failed downloads (< 1KB)
                if os.path.getsize(pdf_path) < 1024:
                    if stubs_sc:
                        judge_stubs = os.path.join(stubs_sc, judge_name)
                        os.makedirs(judge_stubs, exist_ok=True)
                        shutil.move(pdf_path, os.path.join(judge_stubs, pdf_filename))
                        print(f"  [Quarantine] Moved SC stub file {pdf_filename} to {judge_stubs}")
                    continue

                try:
                    doc = fitz.open(pdf_path)
                    full_text = ""
                    for page in doc:
                        full_text += page.get_text() + "\n"
                    
                    clean_txt = self.clean_text(full_text)
                    heuristics = self.extract_heuristics(clean_txt)

                    # Extract case number and case type from the filename (e.g. c.a._1032_2018.pdf)
                    filename_clean = pdf_filename.lower().replace(".pdf", "")
                    
                    type_map = {
                        "c.a.": "Civil Appeal",
                        "c.p.": "Civil Petition",
                        "c.p.l.a.": "Civil Petition for Leave to Appeal",
                        "crl.a.": "Criminal Appeal",
                        "crl.p.": "Criminal Petition",
                        "const.p.": "Constitution Petition",
                        "s.m.c.": "Suo Motu Case",
                        "i.c.a.": "Intra Court Appeal",
                        "crl.m.a.": "Criminal Miscellaneous Application",
                        "h.r.c.": "Human Rights Case"
                    }

                    prefix_match = re.match(r"^([a-z\.]+)", filename_clean)
                    abbrev = prefix_match.group(1) if prefix_match else ""
                    case_type = type_map.get(abbrev, "Supreme Court Judgment")

                    year_match = re.search(r"_(19\d{2}|20\d{2})", filename_clean)
                    year = year_match.group(1) if year_match else "Unknown"

                    if year_match:
                        start_idx = len(abbrev)
                        end_idx = year_match.start()
                        case_num_raw = filename_clean[start_idx:end_idx].strip("_")
                        case_num = case_num_raw.replace("_", "/").upper()
                        case_number = f"{case_type} No. {case_num} of {year}"
                    else:
                        case_number = filename_clean.upper()

                    # Heuristic for case title: search for "Petitioner Versus Respondent" pattern
                    title_match = re.search(r"([A-Za-z0-9\s,\(\)\.]{3,100})\s+(Versus|Vs\.?)\s+([A-Za-z0-9\s,\(\)\.]{3,100})", clean_txt, re.IGNORECASE)
                    if title_match:
                        petitioner = re.sub(r'\s+', ' ', title_match.group(1).strip())
                        respondent = re.sub(r'\s+', ' ', title_match.group(3).strip())
                        case_title = f"{petitioner} Vs. {respondent}"
                        if len(case_title) > 200:
                            case_title = case_title[:200] + "..."
                    else:
                        case_title = f"{case_number}"

                    # Try to extract precise date from text
                    date_match = re.search(r"(?:Decided on|Date of hearing|Date of Judgment|Heard on)[:\s]*(\d{1,2}[-/\.]\d{1,2}[-/\.]\d{4})", clean_txt, re.IGNORECASE)
                    order_date = date_match.group(1).strip() if date_match else year

                    normalized_key = f"sc_{judge_name}_{filename_clean}"
                    doc_id = hashlib.md5(normalized_key.encode()).hexdigest()

                    meta = JudgmentMetadata(
                        case_id=filename_clean,
                        case_title=case_title,
                        case_number=case_number,
                        court="Supreme Court of Pakistan",
                        author_judge=judge_name,
                        judgment_type=case_type,
                        order_date=order_date,
                        outcome=heuristics["outcome"],
                        referenced_laws=heuristics["referenced_laws"],
                        advocates=heuristics["advocates"],
                        source_filename=os.path.join(judge_name, pdf_filename)
                    )

                    yield Document(
                        doc_id=doc_id,
                        doc_type="judgment",
                        title=meta.case_title,
                        content=clean_txt,
                        metadata=meta.model_dump()
                    )

                    # Move to archive upon successful processing (control returns here after yield)
                    if archive_sc:
                        judge_archive = os.path.join(archive_sc, judge_name)
                        os.makedirs(judge_archive, exist_ok=True)
                        shutil.move(pdf_path, os.path.join(judge_archive, pdf_filename))
                        print(f"  [Archive] Moved processed SC PDF {pdf_filename} to {judge_archive}")

                except Exception as e:
                    print(f"Error parsing SC PDF {pdf_filename} under {judge_name}: {e}")
                    if errors_sc:
                        judge_errors = os.path.join(errors_sc, judge_name)
                        os.makedirs(judge_errors, exist_ok=True)
                        shutil.move(pdf_path, os.path.join(judge_errors, pdf_filename))
                        print(f"  [Quarantine] Moved faulty SC PDF {pdf_filename} to {judge_errors}")
