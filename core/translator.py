import re
import urllib.request
import urllib.parse
import json
from typing import Optional, Tuple, Dict

# In-memory translation and language detection cache
_translation_cache: Dict[str, Tuple[str, Optional[str]]] = {}

SERBIAN_CYRILLIC_CHARS = re.compile(r"[ђјљњћџЂЈЉЊЋЏ]")
SERBIAN_LATIN_CHARS = re.compile(r"[čćđšžČĆĐŠŽ]")
CYRILLIC_PATTERN = re.compile(r"[\u0400-\u04FF]")
CJK_PATTERN = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]")
RUSSIAN_UKRAINIAN_EXCLUSIVE = re.compile(r"[ыэъёщяюьієїґўЫЭЪЁЩЯЮЬІЄЇҐЎ]")

SERBIAN_STOPWORDS = {
    "da", "ne", "je", "sam", "smo", "ste", "su", "kako", "gde", "sta", "sto",
    "dobro", "hvala", "molim", "izvolite", "dan", "noc", "vece", "igra", "nema", "ima", "idemo",
    "sve", "mnogo", "ovde", "tamo", "za", "od", "do", "sa", "na", "u", "i",
    "ili", "ali", "vec", "kad", "ako", "brat", "druze", "prijatelju", "pozdrav",
    "lepo", "super", "ko", "zasto", "vidimo", "radi", "hocu", "necu", "moze",
    "sutra", "danas", "kazi", "gledaj", "dodji", "stani", "brate", "pazi", "brzo",
    "srpski", "srpska", "srpsko", "srpske", "srpskom", "jezik", "jezika", "jeziku",
    "strance", "stranci", "knjiga", "tekst", "rec", "reci", "reč", "reči",
    "nauci", "naucimo", "naucite", "usluzno", "pecenje", "kupljeno", "kupljenog",
    "govor", "govori", "akcenat", "akcenta", "vitez", "vitezovi"
}

COMMON_ENGLISH_WORDS = {
    "the", "be", "to", "of", "and", "a", "in", "that", "have", "i", "it", "for",
    "not", "on", "with", "he", "as", "you", "do", "at", "this", "but", "his",
    "by", "from", "they", "we", "say", "her", "she", "or", "an", "will", "my",
    "one", "all", "would", "there", "their", "what", "so", "up", "out", "if",
    "about", "who", "get", "which", "go", "me", "when", "make", "can", "like",
    "time", "no", "just", "him", "know", "take", "people", "into", "year", "your",
    "good", "some", "could", "them", "see", "other", "than", "then", "now", "look",
    "only", "come", "its", "over", "think", "also", "back", "after", "use", "two",
    "how", "our", "work", "first", "well", "way", "even", "new", "want", "because",
    "any", "these", "give", "day", "most", "us",
    # Gaming terms common in Dota 2, CS2, etc.
    "play", "settings", "options", "attack", "speed", "damage", "armor", "health",
    "mana", "inventory", "level", "kill", "death", "assist", "gold", "items",
    "victory", "defeat", "match", "start", "quit", "exit", "ping", "fps", "hero",
    "target", "strength", "agility", "intelligence", "score", "respawn", "buyback",
    "game", "talent", "chat", "mute", "unmute", "report", "stats", "rank",
    "keyboard", "layout", "online", "download", "free", "google", "search", "images", "web"
}

COMMON_RUSSIAN_UI = {
    "картинки", "новости", "видео", "покупки", "инструменты", "поиск", "вкладка",
    "настройки", "сохранить", "отмена", "войти", "выход", "закрыть", "ок"
}

def is_definitely_english(text: str) -> bool:
    """Fast check to identify pure English text without any Slavic/Serbian markers."""
    cleaned = text.strip().lower()
    if CYRILLIC_PATTERN.search(cleaned) or SERBIAN_LATIN_CHARS.search(cleaned):
        return False
    words = set(re.findall(r"\b[a-zA-Z]+\b", cleaned))
    if not words:
        return False
    if words.intersection(COMMON_ENGLISH_WORDS) and not words.intersection(SERBIAN_STOPWORDS):
        return True
    return False

def is_potential_source_language(text: str, source_lang: str) -> bool:
    """
    Ultra-fast 0ms local pre-filter to reject non-candidate phrases
    BEFORE making any HTTP requests to Google Translate.
    """
    cleaned = text.strip()
    if len(cleaned) < 2:
        return False
    if not re.search(r"\w", cleaned):
        return False

    if source_lang == "sr":
        lower = cleaned.lower()
        if is_definitely_english(lower):
            return False

        # Reject Russian/Ukrainian exclusive letters (я, ю, ы, э, ё, щ, ь, ъ)
        if RUSSIAN_UKRAINIAN_EXCLUSIVE.search(lower):
            return False

        # Unique Serbian Cyrillic or Latin letters
        if SERBIAN_CYRILLIC_CHARS.search(lower) or SERBIAN_LATIN_CHARS.search(lower):
            return True

        words = set(re.findall(r"\b\w+\b", lower))
        if words and words.intersection(SERBIAN_STOPWORDS):
            return True

        # Any other Cyrillic without Russian-exclusive letters
        has_cyrillic = bool(CYRILLIC_PATTERN.search(lower))
        if has_cyrillic:
            if words.intersection(COMMON_RUSSIAN_UI):
                return False
            return True

        # Pure Latin text without diacritics
        if bool(re.search(r"[a-zA-Z]", lower)):
            return bool(words.intersection(SERBIAN_STOPWORDS))

        return False

    return True

def translate_and_detect_lang(
    text: str,
    source_lang: str = "auto",
    target_lang: str = "ru"
) -> Tuple[Optional[str], Optional[str]]:
    """
    Translates text and detects its source language using Google GTX endpoint with caching.
    Uses sl=auto to allow true language detection.
    Returns: (translated_text, detected_source_lang)
    """
    cleaned = text.strip()
    if not cleaned or len(cleaned) < 2:
        return None, None

    # If user selected Serbian and the text is definitely English, skip network request
    if source_lang == "sr" and is_definitely_english(cleaned):
        return None, "en"

    cache_key = f"{target_lang}:{cleaned}"
    if cache_key in _translation_cache:
        return _translation_cache[cache_key]

    try:
        q = urllib.parse.quote(cleaned)
        # Always use sl=auto so Google detects the true language of the snippet
        url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl={target_lang}&dt=t&q={q}"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        )
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            translated = "".join([part[0] for part in data[0] if part and part[0]]).strip()

            detected_lang = None
            if len(data) > 2 and isinstance(data[2], str):
                detected_lang = data[2].lower()
            elif len(data) > 8 and data[8] and data[8][0]:
                detected_lang = str(data[8][0][0]).lower()

            _translation_cache[cache_key] = (translated, detected_lang)
            return translated, detected_lang
    except Exception:
        # Fallback to local dictionary if offline
        from core.dictionary import translate_phrase_or_tokens
        local_trans = translate_phrase_or_tokens(cleaned, sl=source_lang, tl=target_lang)
        detected = detect_language_heuristic(cleaned)
        return local_trans, detected

def detect_language_heuristic(text: str) -> str:
    """Fast offline heuristic language detection."""
    cleaned = text.strip().lower()

    if is_definitely_english(cleaned):
        return "en"

    if SERBIAN_CYRILLIC_CHARS.search(cleaned):
        return "sr"
    if SERBIAN_LATIN_CHARS.search(cleaned):
        return "sr"

    words = set(re.findall(r"\b\w+\b", cleaned))
    if words and words.intersection(SERBIAN_STOPWORDS):
        return "sr"

    if CYRILLIC_PATTERN.search(cleaned):
        if not RUSSIAN_UKRAINIAN_EXCLUSIVE.search(cleaned):
            return "sr"
        return "ru"

    if CJK_PATTERN.search(cleaned):
        return "zh"

    if bool(re.search(r"[a-zA-Z]", cleaned)):
        return "en"

    return "auto"

def matches_source_language(
    detected_lang: Optional[str],
    text: str,
    target_source_lang: str
) -> bool:
    """
    Strict filter: returns True ONLY if text matches the chosen target_source_lang.
    If target_source_lang is 'sr', English text is strictly REJECTED.
    """
    if not text or len(text.strip()) < 2:
        return False

    cleaned = text.strip().lower()

    if target_source_lang == "auto":
        # Don't translate if already in Russian / target language
        return detected_lang != "ru"

    # Specific handling for Serbian ('sr')
    if target_source_lang == "sr":
        # Reject English immediately
        if is_definitely_english(cleaned):
            return False
        if detected_lang == "en":
            return False

        # Serbo-Croatian family codes detected by APIs
        if detected_lang in ("sr", "hr", "bs", "srp", "cnr", "mk"):
            return True

        # Unique Serbian Cyrillic letters (ђ, ј, љ, њ, ћ, џ)
        if SERBIAN_CYRILLIC_CHARS.search(cleaned):
            return True

        # Serbian Latin letters (č, ć, đ, š, ž)
        if SERBIAN_LATIN_CHARS.search(cleaned):
            return True

        # Any Cyrillic text without Russian/Ukrainian exclusive letters
        if CYRILLIC_PATTERN.search(cleaned) and not RUSSIAN_UKRAINIAN_EXCLUSIVE.search(cleaned):
            return True

        # Check Serbian stop words
        words = set(re.findall(r"\b\w+\b", cleaned))
        if words and words.intersection(SERBIAN_STOPWORDS):
            return True

        return False

    # Specific handling for English ('en')
    if target_source_lang == "en":
        if detected_lang == "en":
            return True
        if bool(re.search(r"[a-zA-Z]", cleaned)) and not CYRILLIC_PATTERN.search(cleaned) and not CJK_PATTERN.search(cleaned):
            return True
        return False

    # Specific handling for Russian ('ru')
    if target_source_lang == "ru":
        if detected_lang == "ru":
            return True
        has_cyrillic = bool(CYRILLIC_PATTERN.search(cleaned))
        has_serbian = bool(SERBIAN_CYRILLIC_CHARS.search(cleaned))
        return has_cyrillic and not has_serbian

    # Generic language code match
    if detected_lang:
        return detected_lang == target_source_lang or detected_lang.startswith(target_source_lang)

    return detect_language_heuristic(cleaned) == target_source_lang
