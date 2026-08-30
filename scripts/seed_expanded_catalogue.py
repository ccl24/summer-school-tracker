"""Add user-requested programs as reviewable records without inventing dates."""
from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROGRAMS = ROOT / "data" / "programs.json"

CATALOGUE = {
    "UChicago": ("https://summer.uchicago.edu/", "校方直属", ["3 Week Immersion", "Pre-College Summer Language Institute", "Research in the Biological Sciences (RIBS)", "Stones and Bones", "Summer College", "Summer Online"]),
    "Penn": ("https://hs.sas.upenn.edu/summer-programs", "校方直属", ["Penn Pre-College Residential Program", "Penn Pre-College Online Program", "Penn Summer Prep", "Penn Summer Academies", "Engineering Summer Academy at Penn (ESAP)"]),
    "Johns Hopkins": ("https://summer.jhu.edu/programs-courses/pre-college/", "校方直属", ["JHU Pre-College: On Campus", "JHU Pre-College: Commuter", "JHU Pre-College: Online", "Explore Engineering Innovation: Online", "Center for Talented Youth", "Summer Term at JHU: On Campus", "Summer Term at JHU: Online"]),
    "Duke": ("https://summersession.duke.edu/high-school-students", "校方直属", ["Duke Summer Session: Online Courses", "Duke Summer Session: Commuter Courses", "Duke High School & Middle School Summer Programs", "Duke Pre-College Lab Week", "Duke Pre-College Online Option", "Duke TIP"]),
    "Northwestern": ("https://sps.northwestern.edu/college-preparation/", "校方直属", ["College Prep Program (CPP): Credit Online", "College Prep Program (CPP): Credit In-person Commuter", "College Prep Program (CPP): Credit In-person Residential", "College Prep e-Focus", "College Prep IN Focus", "Center for Talent Development (CTD)"]),
    "Brown": ("https://precollege.brown.edu/", "校方直属", ["Summer@Brown", "Brown Environmental Leadership Labs (BELL)", "Brown Experiential Education (BEE)", "Brown Leadership Institute", "Brown STEM for Rising 9th and 10th Graders", "Brown Pre-Baccalaureate"]),
    "WashU": ("https://precollege.wustl.edu/", "校方直属", ["High School Summer Academy", "High School Summer Institutes", "High School Summer Launch", "High School Summer Scholars Program", "Exploration Courses"]),
    "Rice": ("https://precollege.rice.edu/", "校方直属（待验证）", ["Rice Visiting Owls Program", "Aerospace & Aviation Academy", "Rice Emerging Leaders in Technology & Engineering (ELITE Tech Campus)", "Tapia STEM Camps", "Urban Sustainability Academy", "Rice University School Mathematics Project"]),
    "Cornell": ("https://sce.cornell.edu/audience/precollege-studies/", "校方直属", ["Cornell Summer Residential Program"]),
    "Columbia": ("https://precollege.sps.columbia.edu/", "校方直属", ["Columbia NYC Residential Summer", "Columbia Online Summer Immersion", "Columbia College Edge (Commuter)", "Columbia Climate School in the Green Mountains"]),
    "Emory": ("https://precollege.emory.edu/", "校方直属", ["Emory Pre-College Program", "Emory Summer College Program"]),
    "USC": ("https://precollege.usc.edu/", "校方直属", ["USC Summer Program", "USC Online Programs for High School Students"]),
    "NYU": ("https://join.nyu.edu/precollege/", "校方直属", ["NYU Online Precollege"]),
    "UCLA": ("https://summer.ucla.edu/high-school-students/", "校方直属", ["UCLA Summer Intensives", "UCLA Summer College Immersion Program", "UCLA Precollege: Python for Economics and Finance", "UCLA Economics Summer Institute", "UCLA Game Lab Summer Institute", "UCLA Design Media Arts Summer Institute"]),
    "UC Berkeley": ("https://precollege.berkeley.edu/", "校方直属", ["Berkeley Pre-College Scholars: Summer Virtual Track", "Berkeley Pre-College Scholars: Summer Residential Track", "Berkeley Summer Computer Science Academy", "Berkeley Changemaker®"]),
    "UCSB": ("https://summer.ucsb.edu/", "校方直属（待验证）", ["MasterScholar Summer Research Program"]),
    "Stanford": ("https://summerinstitutes.spcs.stanford.edu/", "校方直属", ["Stanford Institutes of Medicine Summer Research Program (SIMR)", "Stanford Pre-Collegiate Summer Institutes", "Stanford Summer Humanities Institute"]),
    "Third-party": ("https://www.envisionexperience.com/", "第三方", ["National Youth Leadership Forum: Medicine"]),
}


def record_id(university: str, name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", f"{university}-{name}".lower()).strip("-")


def main() -> None:
    document = json.loads(PROGRAMS.read_text(encoding="utf-8"))
    existing = {item["id"] for item in document["programs"]}
    now = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    added = 0
    for university, (url, operator, names) in CATALOGUE.items():
        for name in names:
            identifier = record_id(university, name)
            if identifier in existing:
                continue
            document["programs"].append({
                "id": identifier, "university": university, "programName": name, "programUrl": url,
                "applicationOpenDate": None, "deadlines": [], "eligibility": "unknown",
                "eligibilityNote": "This requested program is awaiting verification of current eligibility, international-applicant rules, and application dates.",
                "eligibilitySourceUrl": url, "operator": operator, "status": "unknown", "sourceUrl": url,
                "sourceText": "Imported from the requested programme catalogue; no application date is published until an official programme page is verified.",
                "lastCheckedAt": now, "lastChangedAt": now, "reviewState": "needs_review"
            })
            existing.add(identifier); added += 1
    PROGRAMS.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Added {added} requested programme record(s).")


if __name__ == "__main__":
    main()
