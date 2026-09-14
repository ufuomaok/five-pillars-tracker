import re
from typing import Optional

_BAND_RE = re.compile(r"\bband\s*[-:]?\s*(\d{1,2}[a-d]?)\b", re.IGNORECASE)


def parse_band(title: Optional[str]) -> Optional[str]:
    if not title:
        return None
    match = _BAND_RE.search(title)
    if not match:
        return None
    return f"Band {match.group(1).lower()}"


_MONEY_RE = re.compile(r"£\s*([\d,]+(?:\.\d{1,2})?)")


def parse_salary(salary_text: Optional[str]) -> tuple[Optional[float], Optional[float], Optional[str]]:
    if not salary_text:
        return None, None, None
    amounts = [float(m.replace(",", "")) for m in _MONEY_RE.findall(salary_text)]
    if not amounts:
        return None, None, None

    text_lower = salary_text.lower()
    if "hour" in text_lower:
        period = "hour"
    elif "day" in text_lower:
        period = "day"
    elif "year" in text_lower or "annum" in text_lower:
        period = "year"
    else:
        period = None

    return min(amounts), max(amounts), period


def normalise_working_pattern(working_pattern: Optional[str]) -> Optional[str]:
    if not working_pattern:
        return None
    options = {opt.strip().lower() for opt in working_pattern.split(",") if opt.strip()}
    if options == {"full time"}:
        return "full_time"
    if options == {"part time"}:
        return "part_time"
    return "flexible"


_WHITESPACE_RE = re.compile(r"\s+")


def normalise_employer(employer: Optional[str]) -> Optional[str]:
    if not employer:
        return None
    text = employer.strip()
    text = text.replace("’", "'").replace("‘", "'")
    text = text.replace("–", "-").replace("—", "-")
    text = _WHITESPACE_RE.sub(" ", text)
    return text or None


_ALB_NAMES = [
    "nhs england",
    "nhs business services authority",
    "nhs blood and transplant",
    "nhs resolution",
    "nhs digital",
    "nhs counter fraud authority",
    "uk health security agency",
    "care quality commission",
    "health education england",
    "health research authority",
    "human fertilisation and embryology authority",
    "human tissue authority",
    "medicines and healthcare products regulatory agency",
    "national institute for health and care excellence",
    "healthcare safety investigation branch",
]

_DEVOLVED_NATION_NAMES = [
    "health board", "public health wales", "nhs wales", "velindre",
    "nhs scotland", "health and social care trust",
    "health and social care board",
]

_ORG_TYPE_RULES: list[tuple[str, list[str]]] = [
    ("icb", ["integrated care board", r"\bicb\b"]),
    ("ambulance", ["ambulance service", "ambulance nhs", "ambulance trust"]),
    ("mental_health", ["mental health"]),
    ("community", ["community health", "community healthcare", "community nhs"]),
    ("primary_care", [
        "medical centre", "medical practice", "health centre", "surgery",
        "group practice", "gp practice", "primary care network",
        "gp federation", "gp alliance", "healthcare partnership",
    ]),
]

_ACUTE_MARKERS = [
    "nhs foundation trust", "nhs trust", r"\bnhs\s*ft\b", "foundation trust",
    "university hospital", "teaching hospital", "hospitals trust",
]


def classify_org_type(employer: Optional[str]) -> Optional[str]:
    if not employer:
        return None
    text = employer.lower()

    for org_type, keywords in _ORG_TYPE_RULES:
        if any(re.search(kw, text) for kw in keywords):
            return org_type

    if any(name in text for name in _DEVOLVED_NATION_NAMES):
        return "other"

    if any(alb in text for alb in _ALB_NAMES):
        return "arms_length_body"

    if any(re.search(marker, text) for marker in _ACUTE_MARKERS):
        return "acute"

    return "other"


_POSTCODE_AREA_REGION: dict[str, str] = {
    "NE": "North East and Yorkshire", "SR": "North East and Yorkshire",
    "DH": "North East and Yorkshire", "DL": "North East and Yorkshire",
    "TS": "North East and Yorkshire", "LS": "North East and Yorkshire",
    "BD": "North East and Yorkshire", "HD": "North East and Yorkshire",
    "HX": "North East and Yorkshire", "WF": "North East and Yorkshire",
    "YO": "North East and Yorkshire", "HG": "North East and Yorkshire",
    "HU": "North East and Yorkshire", "DN": "North East and Yorkshire",
    "S": "North East and Yorkshire",
    "CA": "North West", "LA": "North West", "PR": "North West",
    "FY": "North West", "BB": "North West", "L": "North West",
    "WA": "North West", "WN": "North West", "BL": "North West",
    "OL": "North West", "M": "North West", "SK": "North West",
    "CH": "North West", "CW": "North West", "ST": "North West",
    "DE": "Midlands", "NG": "Midlands", "LE": "Midlands",
    "LN": "Midlands", "NN": "Midlands", "CV": "Midlands",
    "WS": "Midlands", "WV": "Midlands", "DY": "Midlands",
    "B": "Midlands", "TF": "Midlands", "SY": "Midlands",
    "HR": "Midlands", "WR": "Midlands", "PE": "Midlands",
    "CB": "East of England", "IP": "East of England",
    "NR": "East of England", "CO": "East of England",
    "CM": "East of England", "SG": "East of England",
    "AL": "East of England", "LU": "East of England",
    "SS": "East of England", "HP": "East of England",
    "E": "London", "EC": "London", "N": "London", "NW": "London",
    "SE": "London", "SW": "London", "W": "London", "WC": "London",
    "BR": "London", "CR": "London", "DA": "London", "EN": "London",
    "HA": "London", "IG": "London", "KT": "London", "RM": "London",
    "SM": "London", "TW": "London", "UB": "London", "WD": "London",
    "OX": "South East", "RG": "South East", "SL": "South East",
    "GU": "South East", "PO": "South East", "SO": "South East",
    "BN": "South East", "TN": "South East", "ME": "South East",
    "CT": "South East", "MK": "South East",
    "GL": "South West", "BA": "South West", "BS": "South West",
    "SN": "South West", "SP": "South West", "DT": "South West",
    "EX": "South West", "TA": "South West", "TQ": "South West",
    "TR": "South West", "PL": "South West",
}

_POSTCODE_RE = re.compile(r"\b([A-Za-z]{1,2})\d")


def _extract_postcode_area(location: str) -> Optional[str]:
    match = _POSTCODE_RE.search(location.upper())
    return match.group(1) if match else None


def derive_region(location: Optional[str], employer: Optional[str] = None) -> Optional[str]:
    if not location:
        return None
    area = _extract_postcode_area(location)
    if area is None:
        return None
    return _POSTCODE_AREA_REGION.get(area)


_PUNCTUATION_RE = re.compile(r"[^\w\s]")


def _normalise_for_key(text: str) -> str:
    text = text.lower()
    text = _PUNCTUATION_RE.sub(" ", text)
    return _WHITESPACE_RE.sub(" ", text).strip()


def build_readvert_key(title: Optional[str], employer_normalised: Optional[str],
                        band: Optional[str]) -> Optional[str]:
    if not title or not employer_normalised:
        return None
    parts = [_normalise_for_key(title), _normalise_for_key(employer_normalised)]
    parts.append(band.lower() if band else "")
    return "|".join(parts)
