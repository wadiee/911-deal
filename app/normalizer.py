import re
from typing import Optional


def normalize_generation(raw: str) -> Optional[str]:
    if not raw:
        return None
    s = raw.lower().strip()

    patterns = {
        "992.2": [r"992\.2", r"992[\s-]?gen[\s-]?2"],
        "992.1": [r"992\.1", r"992[\s-]?gen[\s-]?1", r"\b992\b"],
        "991.2": [r"991\.2", r"991[\s-]?gen[\s-]?2", r"991[\s-]?2"],
        "991.1": [r"991\.1", r"991[\s-]?gen[\s-]?1", r"991[\s-]?1", r"\b991\b"],
        "997.2": [r"997\.2", r"997[\s-]?gen[\s-]?2", r"997[\s-]?2"],
        "997.1": [r"997\.1", r"997[\s-]?gen[\s-]?1", r"\b997\b"],
        "996": [r"\b996\b"],
        "993": [r"\b993\b"],
        "964": [r"\b964\b"],
        # G-series covers 1974–1988: SC, Carrera 3.2, and 930 Turbo
        "G-series": [r"\bg[\s-]?series\b", r"\b930\b", r"\bcarrera\s+3\.2\b", r"\bsc\b"],
        # F-series covers 1964–1973: short-hood and long-hood classics
        "F-series": [r"\bf[\s-]?series\b", r"\bshort[\s-]?hood\b", r"\blong[\s-]?hood\b", r"\bswb\b", r"\blwb\b"],
    }

    for gen, pats in patterns.items():
        for pat in pats:
            if re.search(pat, s):
                return gen
    return None


def normalize_trim(raw: str) -> Optional[str]:
    if not raw:
        return None
    s = raw.lower().strip()
    s = re.sub(r"\s+", " ", s)

    mapping = [
        ("TARGA_4S", ["targa 4s", "targa4s"]),
        ("TARGA_4", ["targa 4", "targa4"]),
        ("CARRERA_4S", ["carrera 4s", "carrera4s", "c4s"]),
        ("CARRERA_4", ["carrera 4", "carrera4", "c4"]),
        ("CARRERA_S", ["carrera s", "carreras", "cs"]),
        ("GTS_4", ["gts 4", "gts4"]),
        ("GTS", ["gts"]),
        ("GT3_RS", ["gt3 rs", "gt3rs"]),
        ("GT3", ["gt3"]),
        ("GT2_RS", ["gt2 rs", "gt2rs"]),
        ("GT2", ["gt2"]),
        ("TURBO_S", ["turbo s", "turbos"]),
        ("TURBO", ["turbo"]),
        ("SPEEDSTER", ["speedster"]),
        ("CARRERA_T", ["carrera t"]),
        ("CARRERA", ["carrera"]),
    ]

    for canonical, aliases in mapping:
        for alias in aliases:
            if alias in s:
                return canonical
    return None


def normalize_transmission(raw: str) -> Optional[str]:
    if not raw:
        return None
    s = raw.lower().strip()

    pdk_signals = ["pdk", "automatic", "auto", "doppelkupplung", "tiptronic"]
    manual_signals = ["manual", "6-speed", "7-speed", "stick", "mt", "6mt", "7mt", "getrag"]

    for sig in manual_signals:
        if sig in s:
            return "MANUAL"
    for sig in pdk_signals:
        if sig in s:
            return "PDK"
    return None


def normalize_body_style(raw: str) -> Optional[str]:
    if not raw:
        return None
    s = raw.lower().strip()

    if "targa" in s:
        return "TARGA"
    if any(x in s for x in ["cab", "cabriolet", "convert", "spider", "spyder"]):
        return "CABRIOLET"
    if any(x in s for x in ["coupe", "coupé", "fastback"]):
        return "COUPE"
    return None


def normalize_seller_type(raw: str) -> Optional[str]:
    if not raw:
        return None
    s = raw.lower().strip()

    if "cpo" in s or "certified" in s:
        return "CPO"
    if "auction" in s:
        return "AUCTION"
    if any(x in s for x in ["dealer", "dealership", "auto group", "motorcars", "motors"]):
        return "DEALER"
    if any(x in s for x in ["private", "owner", "individual", "personal"]):
        return "PRIVATE"
    return None


def infer_generation_from_year(year: int, trim: Optional[str] = None) -> Optional[str]:
    if year >= 2024:
        return "992.2"
    if 2020 <= year <= 2023:
        return "992.1"
    if 2017 <= year <= 2019:
        return "991.2"
    if 2012 <= year <= 2016:
        return "991.1"
    if 2009 <= year <= 2011:
        return "997.2"
    if 2005 <= year <= 2008:
        return "997.1"
    if 1999 <= year <= 2004:
        return "996"
    if 1994 <= year <= 1998:
        return "993"
    if 1989 <= year <= 1993:
        return "964"
    if 1974 <= year <= 1988:
        return "G-series"
    if 1964 <= year <= 1973:
        return "F-series"
    return None
