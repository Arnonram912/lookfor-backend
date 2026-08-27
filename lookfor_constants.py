"""Central user, academic, and display terminology used by API and UI contracts."""

from __future__ import annotations

import re

USER_CATEGORIES = (
    "COLLEGE_STUDENT",
    "SHS_STUDENT",
    "FACULTY",
    "STAFF",
    "ADMIN",
)
ACADEMIC_CLASSIFICATIONS = ("SHS", "TERTIARY", "NON_ACADEMIC")
LEVEL_OPTIONS = (
    "Grade 11",
    "Grade 12",
    "1st Year",
    "2nd Year",
    "3rd Year",
    "4th Year",
)
TERTIARY_TERMS = ("First Semester", "Second Semester")
CLAIMED_DATABASE_STATUSES = ("claimed", "approved", "completed")

USER_CATEGORY_CLASSIFICATION = {
    "COLLEGE_STUDENT": "TERTIARY",
    "SHS_STUDENT": "SHS",
    "FACULTY": "NON_ACADEMIC",
    "STAFF": "NON_ACADEMIC",
    "ADMIN": "NON_ACADEMIC",
}

USER_CATEGORY_LABELS = {
    "COLLEGE_STUDENT": "College student",
    "SHS_STUDENT": "Senior High School student",
    "FACULTY": "Faculty",
    "STAFF": "Staff",
    "ADMIN": "Admin",
}

STATUS_DISPLAY_LABELS = {
    "claimed": "Claimed Item",
    "approved": "Claimed Item",
    "completed": "Claimed Item",
    "pending_surrender": "Pending Surrender",
    "pending_surrendered": "Pending Surrender",
}

_LEVEL_ALIASES = {
    "grade 11": "Grade 11",
    "g11": "Grade 11",
    "grade 12": "Grade 12",
    "g12": "Grade 12",
    "1st year": "1st Year",
    "first year": "1st Year",
    "2nd year": "2nd Year",
    "second year": "2nd Year",
    "3rd year": "3rd Year",
    "third year": "3rd Year",
    "4th year": "4th Year",
    "fourth year": "4th Year",
}

# Unicode letters plus the separators commonly used in names. ``clean_text``
# collapses repeated whitespace before this expression is applied.
NAME_RE = re.compile(r"^[^\W\d_]+(?:[ '-][^\W\d_]+)*$", re.UNICODE)
IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def clean_text(value: object | None) -> str:
    return " ".join(str(value or "").strip().split())


def normalize_user_category(value: object | None) -> str | None:
    normalized = clean_text(value).upper().replace("-", "_").replace(" ", "_")
    aliases = {
        "COLLEGE": "COLLEGE_STUDENT",
        "TERTIARY": "COLLEGE_STUDENT",
        "SENIOR_HIGH_SCHOOL": "SHS_STUDENT",
        "SENIOR_HIGHSCHOOL": "SHS_STUDENT",
        "SHS": "SHS_STUDENT",
    }
    normalized = aliases.get(normalized, normalized)
    return normalized if normalized in USER_CATEGORIES else None


def normalize_level(value: object | None) -> str | None:
    normalized = clean_text(value).casefold()
    # Tertiary spreadsheets use compact year/semester codes such as 1Y1
    # (first year, first semester) and 3Y2 (third year, second semester).
    # A user's semester is represented by their academic batch, while the
    # normalized year is stored in User.level.
    compact_tertiary_level = re.fullmatch(r"([1-4])\s*y\s*[12]", normalized)
    if compact_tertiary_level:
        return {
            "1": "1st Year",
            "2": "2nd Year",
            "3": "3rd Year",
            "4": "4th Year",
        }[compact_tertiary_level.group(1)]
    return _LEVEL_ALIASES.get(normalized)


def tertiary_term_for_level(value: object | None) -> str | None:
    """Return the semester encoded by compact tertiary levels such as 3Y2."""
    normalized = clean_text(value).casefold()
    compact_tertiary_level = re.fullmatch(r"[1-4]\s*y\s*([12])", normalized)
    if not compact_tertiary_level:
        return None
    return "First Semester" if compact_tertiary_level.group(1) == "1" else "Second Semester"


def classification_for_category(category: object | None) -> str | None:
    normalized = normalize_user_category(category)
    return USER_CATEGORY_CLASSIFICATION.get(normalized)


def valid_levels_for_category(category: object | None) -> tuple[str, ...]:
    normalized = normalize_user_category(category)
    if normalized == "SHS_STUDENT":
        return ("Grade 11", "Grade 12")
    if normalized == "COLLEGE_STUDENT":
        return ("1st Year", "2nd Year", "3rd Year", "4th Year")
    return ()


def academic_archive_batch_id(
    classification: object | None,
    academic_year: object | None,
    term_label: object | None,
) -> str:
    normalized_classification = clean_text(classification).upper()
    year = clean_text(academic_year)
    term = clean_text(term_label)
    if normalized_classification == "SHS" and term == "School Year":
        return f"BATCH-{year} School Year"
    stored_term = {
        "First Semester": "1st Semester",
        "Second Semester": "2nd Semester",
    }.get(term)
    if normalized_classification == "TERTIARY" and stored_term:
        return f"BATCH-{year} {stored_term}"
    raise ValueError("Invalid academic archive scope.")


def display_claim_status(value: object | None) -> str:
    normalized = clean_text(value).casefold()
    if normalized in CLAIMED_DATABASE_STATUSES:
        return "Claimed Item"
    return normalized.replace("_", " ").title() if normalized else "Pending"


def infer_legacy_classification(
    *,
    is_admin: bool,
    personnel: object | None,
    department: object | None,
    course: object | None,
    section: object | None,
    level: object | None,
) -> tuple[str | None, str | None, bool]:
    """Return (category, classification, requires_review) using reliable evidence only."""
    personnel_value = clean_text(personnel).casefold()
    if is_admin:
        category = "STAFF" if personnel_value == "staff" else "ADMIN"
        return category, "NON_ACADEMIC", False
    if personnel_value == "faculty":
        return "FACULTY", "NON_ACADEMIC", False
    if personnel_value == "staff":
        return "STAFF", "NON_ACADEMIC", False

    has_department = bool(clean_text(department) and clean_text(department).casefold() != "n/a")
    if has_department and not clean_text(course) and not clean_text(section):
        return "FACULTY", "NON_ACADEMIC", False

    normalized_level = normalize_level(level)
    if normalized_level in {"Grade 11", "Grade 12"}:
        return "SHS_STUDENT", "SHS", False
    if normalized_level in {"1st Year", "2nd Year", "3rd Year", "4th Year"}:
        return "COLLEGE_STUDENT", "TERTIARY", False
    return None, None, True
