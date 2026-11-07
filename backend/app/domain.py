"""Conservative, deterministic sealed-product identification. No fuzzy merging."""
from dataclasses import dataclass
import hashlib
import html
import json
import re
import unicodedata

from bs4 import BeautifulSoup

from app.adapters.base import SourceOffer


def plain(value: str) -> str:
    return " ".join(BeautifulSoup(html.unescape(value or ""), "html.parser").get_text(" ").split())


def normalized(value: str) -> str:
    value = unicodedata.normalize("NFKD", plain(value).lower())
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value).split())


def search_normalized(value: str) -> str:
    value = re.sub(r"\b(op|eb|prb|fb|sb)\s*(\d{2})\b", r"\1\2", normalized(value))
    return re.sub(r"\b(?:bt|b)\s*(\d{1,2})\b", lambda match: f"b{int(match[1]):02d}", value)


def identify_game(text: str) -> str | None:
    text = normalized(text)
    if "dragon ball" in text or "dragonball" in text or "dbscg" in text or re.search(r"\bdbs\b", text):
        fusion = bool("fusion world" in text or re.search(r"\b(?:fb|sb)\s?\d{2}\b", text))
        masters = bool(re.search(r"\b(?:masters|zenkai|unison warrior)\b|\b(?:bt|b)\s?\d{1,2}\b", text))
        if fusion and masters:
            return None  # Contradictory product lines must not be guessed.
        if fusion:
            return "dragon-ball-fusion-world"
        return "dragon-ball-masters" if masters else None
    if "one piece" in text or "onepiece" in text:
        return "one-piece"
    if "pokemon" in text:
        return "pokemon"
    return None


LANGUAGES = {
    "de": r"\b(?:de|deu|ger|deutsch|german)\b",
    "en": r"\b(?:en|eng|englisch|english)\b",
    "ja": r"\b(?:jp|jpn|ja|japanisch|japanese)\b",
    "zh": r"\b(?:chn|chinesisch|chinese|china)\b",
    "fr": r"\b(?:fr|franzosisch|french|francais)\b",
    "it": r"\b(?:it|italienisch|italian|italiano)\b",
    "ko": r"\b(?:kr|kor|koreanisch|korean)\b",
}


def identify_language(source: SourceOffer) -> str:
    for text in (source.language_hint, source.variant_label, source.title, source.labels):
        found = [code for code, pattern in LANGUAGES.items() if re.search(pattern, normalized(text))]
        if len(found) == 1:
            return found[0]
        if len(found) > 1:
            return "unknown"
    return "unknown"


def identify_type(text: str) -> str | None:
    text = normalized(text)
    for name, pattern in (
        ("case", r"\b(?:case|karton)\b"),
        ("display", r"\b(?:display|booster box)\b"),
        ("etb", r"\b(?:etb|elite trainer|top trainer)\b"),
        ("bundle", r"\b(?:bundle|booster.*\d+er set)\b"),
        ("blister", r"\bblister\b"),
        ("tin", r"\btins?\b"),
        ("collection", r"\b(?:kollektion|collection|premium box|illustration box|gift box)\b"),
        ("starter_deck", r"\b(?:starter|structure|battle).*deck\b"),
        ("booster", r"\b(?:booster|boosterpack|pack)\b"),
    ):
        if re.search(pattern, text):
            return name
    return None


POKEMON_SETS = {
    "sv09": ("reisegefahrten", "journey together"),
    "sv08": ("sturmische funken", "surging sparks"),
    "sv07": ("stellarkrone", "stellar crown"),
    "sv06": ("maskerade im zwielicht", "twilight masquerade"),
    "sv05": ("gewalten der zeit", "temporal forces"),
    "sv04": ("paradoxrift", "paradox rift"),
    "sv03": ("obsidianflammen", "obsidian flames"),
    "sv02": ("entwicklungen in paldea", "paldea evolved"),
    "sv3pt5": ("pokemon 151", "pokemon karmesin purpur 151"),
}


def identify_set(game: str, title: str) -> tuple[str | None, str | None]:
    text = normalized(title)
    if game in ("one-piece", "dragon-ball-fusion-world", "dragon-ball-masters"):
        prefixes = {"one-piece": "op|eb|prb", "dragon-ball-fusion-world": "fb|sb", "dragon-ball-masters": "bt|b"}[game]
        digits = r"\d{1,2}" if game == "dragon-ball-masters" else r"\d{2}"
        found = {(prefix.replace("bt", "b"), number.zfill(2)) for prefix, number in re.findall(rf"\b({prefixes})\s?({digits})\b", text)}
        if len(found) == 1:
            prefix, number = next(iter(found))
            code = f"{prefix.upper()}-{number}"
            return code, code
        return None, None
    matches = [(code, names[0]) for code, names in POKEMON_SETS.items() if any(name in text for name in names)]
    if len(matches) == 1:
        return matches[0]
    return None, None


def valid_gtin(value: str | None) -> str | None:
    value = str(value or "").strip()
    if not value.isdigit() or len(value) not in (8, 12, 13, 14):
        return None
    total = sum(int(digit) * (3 if index % 2 == 0 else 1) for index, digit in enumerate(reversed(value[:-1])))
    return value.zfill(14) if (10 - total % 10) % 10 == int(value[-1]) else None


@dataclass
class ProductIdentity:
    game: str
    set_code: str | None
    set_name: str | None
    language: str
    product_type: str
    booster_count: int | None
    condition: str
    edition: str
    gtin: str | None
    identity_key: str
    confidence: str


def classify(source: SourceOffer, merchant_slug: str) -> ProductIdentity | None:
    title = normalized(source.title)
    # Graded singles can contain set names such as "Red Collection" or "Booster".
    # Their card numbers and grading labels take precedence over those words.
    if re.search(r"\b\d{1,3}\s*/\s*\d{1,3}\b", source.title) or re.search(
        r"\b(?:graded|gegradet\w*|slabs?)\b|\b(?:psa|bgs|cgc|aog|sgc)\s+\d", title
    ):
        return None
    if re.search(r"\b(?:sleeves?|spielmatte|playmat|deckbox|binder|album|acrylcase|acrylic|acryl|schutzhulle|schutzbox|display protector|einzelkarte|single card|live break|rip and ship|rip ship|repack|mystery|geoffnet|opened|unsealed|resealed|gebraucht|used)\b", title):
        return None
    # A specific product title takes precedence over broad mixed shop categories.
    game = identify_game(source.title) or identify_game(source.title + " " + source.labels)
    if not game:
        return None
    # Reject numbered single cards, even when a category contains the word booster.
    if re.search(r"\b(?:op|fb|sb|eb|prb)\s?\d{2}\s?\d{3}\b|\b(?:bt|b)\s?\d{1,2}\s?\d{3}\b", title):
        return None
    kind = identify_type(source.variant_label) or identify_type(source.title) or identify_type(source.product_type_hint)
    if not kind:
        # A mixed "Booster & Displays" category says nothing about the offer's unit.
        # Prefer a short, explicit product heading in the actual description.
        heading = plain(source.description)[:240]
        heading = re.split(r"\b(?:enthält|contains|beinhaltet|Inhalt:)\b", heading, maxsplit=1, flags=re.I)[0]
        inferred = identify_type(heading)
        if inferred and inferred != "booster":
            kind = inferred
    if not kind:
        return None
    language = identify_language(source)
    count = None
    if kind == "booster":
        count = 1
        quantity_title = source.variant_label or re.sub(r"\b(?:OP|EB|PRB|FB|SB)[\s-]?\d{2}\b|\b(?:BT|B)[\s-]?\d{1,2}\b", "", source.title, flags=re.I)
        if game == "pokemon":
            quantity_title = re.sub(r"\b151\b", "set", quantity_title)
        multi = re.search(r"\b(\d+)\s*(?:x|er)?\s*(?:booster|packs?)\b", quantity_title, re.I)
        if multi:
            count = int(multi[1])
            if count > 1:
                kind = "bundle"
    else:
        # Read explicit pack counts only; never infer a display size from the game.
        texts = [source.title, plain(source.description)]
        nested_display = kind == "display" and bool(re.search(r"\b(?:booster bundle|blister|tins?)\b", title))
        for text in texts:
            explicit_total = re.search(r"\b(?:insgesamt|total(?: of)?)\s*(\d{1,3})\s*(?:booster(?:packs?)?|packs?)\b", text, re.I)
            if explicit_total:
                count = int(explicit_total[1])
                break
            if kind == "case" or nested_display:
                continue  # "12 displays of 24 packs" is not a total pack count.
            if game == "pokemon":
                # 151 is an expansion name, never evidence of 151 included packs.
                text = re.sub(r"\b151\b", "set", text)
            matches = re.findall(r"\b(\d{1,3})\s*(?:x\s*)?(?:booster(?:packs?)?|packs?|packungen)\b(?!\s*(?:box(?:es|en)?|displays?)\b)", text, re.I)
            if len(matches) == 1 and 1 <= int(matches[0]) <= 999:
                count = int(matches[0])
                break
    set_code, set_name = identify_set(game, source.title)
    special = [word for word in ("enhanced", "premium", "limited", "collector", "reprint", "first edition", "1 auflage", "2 auflage", "bonus", "god pack") if word in title]
    edition = "+".join(special) if special else "standard"
    gtin = valid_gtin(source.gtin)
    condition = "damaged_sealed" if re.search(r"\b(?:beschadigt|damaged|dented)\b", title) else "sealed"
    dimensions = [game, set_code, language, kind, count, condition, edition]
    confidence = "isolated"
    if gtin and language != "unknown":
        key = ["gtin", gtin, *dimensions]
        confidence = "gtin"
    elif game in ("one-piece", "dragon-ball-fusion-world", "dragon-ball-masters") and set_code and language != "unknown" and count is not None and kind in ("booster", "display") and edition == "standard" and normalized(source.variant_label) in ("", "display", "booster"):
        key = ["exact_attributes", *dimensions]
        confidence = "exact_attributes"
    else:
        # Keep uncertain mappings separate by merchant and source variant.
        key = ["isolated", merchant_slug, source.external_id, *dimensions]
    identity_key = hashlib.sha256(json.dumps(key, ensure_ascii=True).encode()).hexdigest()
    return ProductIdentity(game, set_code, set_name, language, kind, count, condition, edition, gtin, identity_key, confidence)
