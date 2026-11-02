from __future__ import annotations

import hashlib
import re
import unicodedata

ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
ZERO_WIDTH = re.compile(r"[\u200b-\u200f\u202a-\u202e\ufeff]")

# Examples accepted: 3905 V 3750, 3905V3750, 3905 / V / 3750
FREQUENCY_RE = re.compile(
    r"(?<!\d)(\d{3,5})\s*[/|,:;\-]?\s*([HVLR])\s*[/|,:;\-]?\s*(\d{3,6})(?!\d)",
    re.IGNORECASE,
)
# Byte pairs separated by spaces, optionally with punctuation. Avoid treating normal words as keys.
HEX_RE = re.compile(r"(?<![0-9A-F])((?:[0-9A-F]{2}[\s:,-]*){6,32})(?![0-9A-F])", re.IGNORECASE)
SATELLITE_RE = re.compile(
    r"(?im)(?:^|[\n|•])\s*([A-Z][A-Za-z0-9+./()'& -]{2,80}?(?:\d{1,3}(?:\.\d+)?\s*[EW]|C-Band|Ku-Band|Ka-Band))\s*(?:$|[\n|•])"
)


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).translate(ARABIC_DIGITS)
    text = ZERO_WIDTH.sub("", text)
    return text.replace("\u00a0", " ")


def clean_code(raw: str) -> str:
    return " ".join(re.findall(r"[0-9A-Fa-f]{2}", raw)).upper()


def satellite_from(text: str, start: int, end: int) -> str | None:
    # Prefer a line containing a satellite marker near the frequency.
    window = text[max(0, start - 220): min(len(text), end + 120)]
    lines = [x.strip(" \t|•-*_") for x in window.splitlines() if x.strip()]
    for line in lines:
        if re.search(r"\d{1,3}(?:\.\d+)?\s*[EW]|C[- ]?Band|Ku[- ]?Band|Ka[- ]?Band", line, re.I):
            line = re.sub(r"\s+", " ", line)
            if len(line) <= 120:
                return line
    match = SATELLITE_RE.search(window)
    return match.group(1).strip() if match else None


def parse_text(text: str, source_url: str) -> list[dict]:
    text = normalize(text)
    results: list[dict] = []
    for freq_match in FREQUENCY_RE.finditer(text):
        frequency = f"{freq_match.group(1)} {freq_match.group(2).upper()} {freq_match.group(3)}"
        # Search for a key in the same nearby post/paragraph.
        window = text[max(0, freq_match.start() - 500): min(len(text), freq_match.end() + 700)]
        # Mask the frequency itself so values such as 37 50 are not mistaken for hex bytes.
        local_start = freq_match.start() - max(0, freq_match.start() - 500)
        local_end = local_start + (freq_match.end() - freq_match.start())
        window = window[:local_start] + (" " * (local_end - local_start)) + window[local_end:]
        key_match = HEX_RE.search(window)
        if not key_match:
            continue
        code = clean_code(key_match.group(1))
        if len(code.split()) < 6:
            continue
        satellite = satellite_from(text, freq_match.start(), freq_match.end())
        if not satellite:
            continue
        item = {
            "satellite": satellite,
            "frequency": frequency,
            "code": code,
            "source": source_url,
        }
        item["id"] = hashlib.sha256(
            f"{satellite}|{frequency}|{code}".lower().encode("utf-8")
        ).hexdigest()[:16]
        if not any(x["id"] == item["id"] for x in results):
            results.append(item)
    return results
