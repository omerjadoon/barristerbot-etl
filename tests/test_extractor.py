import pytest
from preprocessing.extractor import LegalExtractor

def test_clean_text():
    extractor = LegalExtractor()
    raw_text = "Only for viewing purpose. Contact office for certified copy. \n\nPage 1 of 5 \n PESHAWAR HIGH COURT\n\nJUDGMENT SHEET\n  Some   actual text  "
    cleaned = extractor.clean_text(raw_text)
    assert "Only for viewing purpose" not in cleaned
    assert "PESHAWAR HIGH COURT" not in cleaned
    assert "JUDGMENT SHEET" not in cleaned
    assert "Page 1 of 5" not in cleaned
    assert "Some actual text" in cleaned

def test_extract_heuristics_referenced_laws():
    extractor = LegalExtractor()
    text = "The petitioner is accused under Section 302 of the Pakistan Penal Code and Section 249-A of the Code of Criminal Procedure."
    heuristics = extractor.extract_heuristics(text)
    # Check referenced laws are extracted and normalized
    assert "PPC Section 302" in heuristics["referenced_laws"]
    assert "CrPC Section 249-A" in heuristics["referenced_laws"]

def test_extract_heuristics_advocates():
    extractor = LegalExtractor()
    # Using 'M/s' without dot to match the extractor's specific regex capture logic
    text = "Mr. Khalid Rehman, Advocate for the petitioner. M/s Tariq Khan, Advocate for the respondent."
    heuristics = extractor.extract_heuristics(text)
    advs = heuristics["advocates"]
    assert len(advs) == 2
    assert advs[0].name == "Khalid Rehman"
    assert advs[0].role == "petitioner"
    assert advs[1].name == "Tariq Khan"
    assert advs[1].role == "respondent"

def test_extract_heuristics_outcomes():
    extractor = LegalExtractor()
    
    t1 = "For the reasons stated above, this petition is dismissed."
    assert extractor.extract_heuristics(t1)["outcome"] == "Dismissed"
    
    # In the current implementation, 'allowed' checks before 'acquitted', so this returns 'Allowed'
    t2 = "The appeal is allowed and the convict is acquitted."
    assert extractor.extract_heuristics(t2)["outcome"] == "Allowed"

    t3 = "The convict is acquitted of all charges."
    assert extractor.extract_heuristics(t3)["outcome"] == "Acquitted"
    
    t4 = "Consequently, the ad-interim bail is granted to the petitioner."
    assert extractor.extract_heuristics(t4)["outcome"] == "Bail Granted"
