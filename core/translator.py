import re
import urllib.request
import urllib.parse
import json
import html
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, Tuple, Dict, List

# Circuit breaker for Google Translate HTTP 429 rate limit
_google_blocked_until = 0.0

def _is_google_available() -> bool:
    return time.time() > _google_blocked_until

def _trip_google_breaker(cooldown_seconds: float = 600.0):
    global _google_blocked_until
    _google_blocked_until = time.time() + cooldown_seconds

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

FILE_EXT_PATTERN = re.compile(
    r"\.(py|json|jsonl|ps1|bat|cmd|sh|bin|exe|dll|txt|md|log|ini|cfg|yaml|yml|toml|cpp|c|h|hpp|rs|go|java|js|ts|html|css|zip|tar|gz|7z|png|jpg|jpeg|gif|svg|webp|ico|mp4|mkv|mp3|wav|ogg)$",
    re.IGNORECASE
)
DATE_SIZE_PATTERN = re.compile(
    r"^[\d\s\.,\:\/\-]+(?:\s*(?:kb|mb|gb|tb|kб|кб|мб|гб|тб|b|k|m|g|k6|к6|%)|\b)?$",
    re.IGNORECASE
)

def is_potential_source_language(text: str, source_lang: str, target_lang: str = "ru") -> bool:
    """
    Ultra-fast 0ms local pre-filter to reject non-candidate phrases
    BEFORE making any HTTP requests to Google Translate.
    """
    cleaned = text.strip()
    if len(cleaned) < 2:
        return False
    # Must contain at least one letter
    if not re.search(r"[a-zA-Z\u0400-\u04FF\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]", cleaned):
        return False

    # Skip pure dates, timestamps, memory/file sizes (e.g. "607 КБ", "25.09.2026 19:52", "100%")
    if DATE_SIZE_PATTERN.match(cleaned):
        return False

    # Skip filenames with extensions (e.g. "train.py", "tokenizer.json", "test_wsl.ps1")
    if FILE_EXT_PATTERN.search(cleaned):
        return False

    lower = cleaned.lower()

    # If target language is Russian, ignore text that is already in Russian
    if target_lang == "ru" and source_lang != "sr":
        has_cyrillic = bool(CYRILLIC_PATTERN.search(lower))
        has_latin = bool(re.search(r"[a-zA-Z]", lower))
        # Pure Cyrillic without Latin is already Russian (e.g. "Дата изменения", "Размер", "Сценарий Windows")
        if has_cyrillic and not has_latin:
            return False

    if source_lang == "auto":
        return True

    if source_lang == "en":
        # English text must contain Latin letters and NOT Cyrillic or CJK
        has_latin = bool(re.search(r"[a-zA-Z]", cleaned))
        has_cyrillic = bool(CYRILLIC_PATTERN.search(cleaned))
        has_cjk = bool(CJK_PATTERN.search(cleaned))
        return has_latin and not has_cyrillic and not has_cjk

    if source_lang == "sr":
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

SERBIAN_FAST_DICT: Dict[str, str] = {
    # Character creation & general UI
    "generalije": "Общие данные",
    "pol": "Пол",
    "muski": "Мужской",
    "muški": "Мужской",
    "zenski": "Женский",
    "ženski": "Женский",
    "datum rodenja": "Дата рождения",
    "datum rođenja": "Дата рождения",
    "ime": "Имя",
    "prezime": "Фамилия",
    "unesite": "Введите",
    "unesite vase ime": "Введите ваше имя",
    "unesite vaše ime": "Введите ваше имя",
    "unesite vase prezime": "Введите вашу фамилию",
    "unesite vaše prezime": "Введите вашу фамилию",
    "unesite datum rodenja": "Введите дату рождения",
    "unesite datum rođenja": "Введите дату рождения",
    "unesite godine": "Введите возраст",
    "godine": "Возраст / Лет",
    "karakter": "Персонаж",
    "kreiranje karaktera": "Создание персонажа",
    "izgled": "Внешность",
    "lice": "Лицо",
    "kosa": "Волосы",
    "brada": "Борода",
    "odeca": "Одежда",
    "odeća": "Одежда",
    "roditelji": "Родители",
    "otac": "Отец",
    "majka": "Мать",
    "sledece": "Далее",
    "sledeće": "Далее",
    "nazad": "Назад",
    "potvrdi": "Подтвердить",
    "potvrdite": "Подтвердите",
    "odustani": "Отмена",
    "ponisti": "Отмена",
    "poništi": "Отмена",
    "sacuvaj": "Сохранить",
    "sačuvaj": "Сохранить",
    "izlaz": "Выход",
    "izadji": "Выйти",
    "izađi": "Выйти",
    "izaberite": "Выберите",
    "izaberi": "Выбрать",
    "prihvati": "Принять",
    "odbij": "Отклонить",
    "zatvori": "Закрыть",
    "otvori": "Открыть",
    "obrisi": "Удалить",
    "obriši": "Удалить",
    "promeni": "Изменить",
    "podesavanja": "Настройки",
    "podešavanja": "Настройки",
    "opcije": "Опции",
    "pomoc": "Помощь",
    "pomoć": "Помощь",
    "pravila": "Правила",
    "korisnik": "Пользователь",
    "lozinka": "Пароль",
    "prijava": "Вход",
    "registracija": "Регистрация",
    "server": "Сервер",
    
    # Inventory & Items & Economy
    "inventar": "Инвентарь",
    "predmet": "Предмет",
    "predmeti": "Предметы",
    "novac": "Деньги",
    "gotovina": "Наличные",
    "banka": "Банк",
    "racun": "Счет",
    "račun": "Счет",
    "stanje": "Баланс",
    "uplata": "Пополнение",
    "isplata": "Снятие",
    "prenos": "Перевод",
    "kupi": "Купить",
    "kupite": "Купите",
    "prodaj": "Продать",
    "prodajte": "Продайте",
    "cena": "Цена",
    "kolicina": "Количество",
    "količina": "Количество",
    "koristi": "Использовать",
    "upotrebi": "Применить",
    "baci": "Выбросить",
    "daj": "Передать",
    "oruzje": "Оружие",
    "oružje": "Оружие",
    "municija": "Патроны",
    "metci": "Пули / Патроны",
    "ranac": "Рюкзак",
    "tezina": "Вес",
    "težina": "Вес",
    "maksimalno": "Максимум",
    
    # Vehicles & Transport
    "vozilo": "Транспорт",
    "kola": "Машина",
    "auto": "Автомобиль",
    "motor": "Двигатель",
    "upali motor": "Завести двигатель",
    "ugasi motor": "Заглушить двигатель",
    "otkljucaj": "Разблокировать",
    "otključaj": "Разблокировать",
    "zakljucaj": "Заблокировать",
    "zaključaj": "Заблокировать",
    "vrata": "Двери",
    "gepek": "Багажник",
    "hauba": "Капот",
    "prozori": "Окна",
    "pojas": "Ремень безопасности",
    "vezi pojas": "Пристегнуть ремень",
    "veži pojas": "Пристегнуть ремень",
    "gorivo": "Топливо",
    "brzina": "Скорость",
    "kilometraza": "Пробег",
    "kilometraža": "Пробег",
    "popravi": "Починить",
    "ocisti": "Очистить",
    "očisti": "Очистить",
    "garaza": "Гараж",
    "garaža": "Гараж",
    "parkiraj": "Припарковать",
    "registruj": "Зарегистрировать",
    
    # Phone, map & communications
    "telefon": "Телефон",
    "poruke": "Сообщения",
    "poruka": "Сообщение",
    "pozivi": "Звонки",
    "poziv": "Звонок",
    "kontakti": "Контакты",
    "kontakt": "Контакт",
    "mapa": "Карта",
    "lokacija": "Местоположение",
    "gps": "GPS Навигация",
    "radio": "Рация / Радио",
    "frekvencija": "Частота",
    "kanal": "Канал",
    
    # Jobs, Factions, Law & RP
    "posao": "Работа",
    "zaposli se": "Устроиться на работу",
    "otkaz": "Увольнение",
    "plata": "Зарплата",
    "policija": "Полиция",
    "bolnica": "Больница",
    "hitna pomoc": "Скорая помощь",
    "hitna pomoć": "Скорая помощь",
    "zdravlje": "Здоровье",
    "oklop": "Броня",
    "pancir": "Бронежилет",
    "kazna": "Штраф",
    "kazne": "Штрафы",
    "plati kaznu": "Оплатить штраф",
    "zatvor": "Тюрьма",
    "hapsenje": "Арест",
    "hapšenje": "Арест",
    "dokumenta": "Документы",
    "licna karta": "Удостоверение личности",
    "lična karta": "Удостоверение личности",
    "vozacka dozvola": "Водительские права",
    "vozačka dozvola": "Водительские права",
    "oruzani list": "Лицензия на оружие",
    "oružani list": "Лицензия на оружие",
    "zdravstvena knjizica": "Медицинская карта",
    "zdravstvena knjižica": "Медицинская карта",
    "dozvola": "Разрешение / Лицензия",
    "dozvole": "Разрешения / Лицензии",
    
    # Common conversational / RP phrases
    "dobar dan": "Добрый день",
    "dobro vece": "Добрый вечер",
    "dobro veče": "Добрый вечер",
    "laku noc": "Спокойной ночи",
    "laku noć": "Спокойной ночи",
    "zdravo": "Привет",
    "cao": "Привет / Пока",
    "ćao": "Привет / Пока",
    "hvala": "Спасибо",
    "molim": "Пожалуйста",
    "izvolite": "Пожалуйста / Держите",
    "dovidjenja": "До свидания",
    "doviđenja": "До свидания",
    "kako si": "Как ты",
    "sta radis": "Что делаешь",
    "šta radiš": "Что делаешь",
    "gde si": "Где ты",
    "ko si ti": "Кто ты",
    "stani": "Стой / Остановись",
    "cekaj": "Подожди",
    "čekaj": "Подожди",
    "idemo": "Пошли / Поехали",
    "brzo": "Быстро",
    "polako": "Медленно / Потише",
    "pazi": "Осторожно / Внимание",
    "ruke u vis": "Руки вверх",
    "ruke gore": "Руки вверх",
    "daj mi": "Дай мне",
    "nemam": "У меня нет",
    "imam": "У меня есть",
    "hocu": "Хочу",
    "necu": "Не хочу",
    "moze": "Можно / Договорились",
    "ne moze": "Нельзя",
    "vazi": "Хорошо / Договорились",
    "važi": "Хорошо / Договорились",
    "naravno": "Конечно",
    "odmah": "Сейчас / Немедленно"
}

ENGLISH_FAST_DICT: Dict[str, str] = {
    "options": "Настройки",
    "settings": "Настройки",
    "play": "Играть",
    "quit": "Выход",
    "exit": "Выход",
    "start": "Старт",
    "resume": "Продолжить",
    "continue": "Продолжить",
    "cancel": "Отмена",
    "confirm": "Подтвердить",
    "back": "Назад",
    "next": "Далее",
    "save": "Сохранить",
    "apply": "Применить",
    "load": "Загрузить",
    "loading": "Загрузка",
    "select": "Выбрать",
    "inventory": "Инвентарь",
    "map": "Карта",
    "help": "Помощь",
    "stats": "Статистика",
    "victory": "Победа",
    "defeat": "Поражение",
    "attack speed": "Скорость атаки",
    "armor": "Броня",
    "health": "Здоровье",
    "mana": "Мана",
    "damage": "Урон",
    "gold": "Золото",
    "level": "Уровень"
}

def _match_case_phrase(src: str, target: str) -> str:
    """Preserves lowercase, Titlecase, or ALL CAPS from source into target."""
    if not src or not target:
        return target
    if src.isupper() and len(src) > 1:
        return target.upper()
    if src[0].isupper():
        return target[0].upper() + target[1:]
    return target

def _lookup_fast_dict(text: str) -> Optional[Tuple[str, str]]:
    """Instant O(1) dictionary lookup for common gaming and UI terms in 0.001 ms."""
    norm = text.strip().lower()
    norm_clean = re.sub(r"[^\w\s]", "", norm).strip()

    if norm in SERBIAN_FAST_DICT:
        return _match_case_phrase(text, SERBIAN_FAST_DICT[norm]), "sr"
    if norm_clean in SERBIAN_FAST_DICT:
        return _match_case_phrase(text, SERBIAN_FAST_DICT[norm_clean]), "sr"

    if norm in ENGLISH_FAST_DICT:
        return _match_case_phrase(text, ENGLISH_FAST_DICT[norm]), "en"
    if norm_clean in ENGLISH_FAST_DICT:
        return _match_case_phrase(text, ENGLISH_FAST_DICT[norm_clean]), "en"

    return None

def batch_translate_and_detect_lang(
    texts: List[str],
    source_lang: str = "auto",
    target_lang: str = "ru"
) -> List[Tuple[Optional[str], Optional[str]]]:
    """
    Ultra-fast batch translation:
    1. Checks in-memory cache (0 ms)
    2. Checks fast local dictionary (0 ms)
    3. If online Google is available, requests batch in a single HTTP call (30-80 ms)
    4. If Google is blocked (HTTP 429), trips circuit breaker and translates unknown phrases
       concurrently via ThreadPoolExecutor with MyMemory/offline dictionary (150-300 ms total).
    """
    if not texts:
        return []

    results: List[Optional[Tuple[Optional[str], Optional[str]]]] = [None] * len(texts)
    uncached_indices: List[int] = []
    uncached_texts: List[str] = []

    for i, t in enumerate(texts):
        cleaned = t.strip()
        if not cleaned or len(cleaned) < 2:
            results[i] = (None, None)
            continue

        cache_key = f"{source_lang}:{target_lang}:{cleaned}"
        if cache_key in _translation_cache:
            results[i] = _translation_cache[cache_key]
            continue

        fast_res = _lookup_fast_dict(cleaned)
        if fast_res:
            _translation_cache[cache_key] = fast_res
            results[i] = fast_res
            continue

        uncached_indices.append(i)
        uncached_texts.append(cleaned.replace("\n", " "))

    if not uncached_texts:
        return [r if r is not None else (None, None) for r in results]

    # If Google is available, attempt batch request
    remaining_indices = []
    remaining_texts = []

    if _is_google_available():
        batch_size = 25
        for b_start in range(0, len(uncached_texts), batch_size):
            b_indices = uncached_indices[b_start:b_start + batch_size]
            b_texts = uncached_texts[b_start:b_start + batch_size]
            joined = "\n".join(b_texts)

            try:
                q = urllib.parse.quote(joined)
                sl_param = "auto" if source_lang == "auto" else source_lang
                url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl={sl_param}&tl={target_lang}&dt=t&q={q}"
                req = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                        "Accept": "*/*"
                    }
                )
                with urllib.request.urlopen(req, timeout=1.8) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    full_translated = "".join([part[0] for part in data[0] if part and part[0]])

                    detected_lang = None
                    if len(data) > 2 and isinstance(data[2], str):
                        detected_lang = data[2].lower()
                    elif len(data) > 8 and data[8] and data[8][0]:
                        detected_lang = str(data[8][0][0]).lower()

                    split_translated = full_translated.split("\n")
                    if len(split_translated) == len(b_texts):
                        for orig_idx, orig_text, trans in zip(b_indices, b_texts, split_translated):
                            trans_clean = trans.strip()
                            cache_key = f"{source_lang}:{target_lang}:{orig_text}"
                            res_tuple = (trans_clean, detected_lang)
                            _translation_cache[cache_key] = res_tuple
                            results[orig_idx] = res_tuple
                    else:
                        remaining_indices.extend(b_indices)
                        remaining_texts.extend(b_texts)
            except Exception:
                # HTTP 429 or network error -> trip circuit breaker for 10 minutes
                _trip_google_breaker(600.0)
                remaining_indices.extend(b_indices)
                remaining_texts.extend(b_texts)
    else:
        remaining_indices = uncached_indices
        remaining_texts = uncached_texts

    # For any remaining items, execute concurrent parallel translations
    if remaining_texts:
        def _worker(idx_text):
            idx, text = idx_text
            tr, det = _translate_fallback(text, source_lang, target_lang)
            return idx, text, tr, det

        with ThreadPoolExecutor(max_workers=min(8, len(remaining_texts))) as executor:
            futures = [executor.submit(_worker, (idx, txt)) for idx, txt in zip(remaining_indices, remaining_texts)]
            for fut in as_completed(futures):
                try:
                    idx, text, tr, det = fut.result()
                    res_tuple = (tr, det)
                    cache_key = f"{source_lang}:{target_lang}:{text}"
                    _translation_cache[cache_key] = res_tuple
                    results[idx] = res_tuple
                except Exception:
                    pass

    return [r if r is not None else (None, None) for r in results]

def _translate_fallback(
    cleaned: str,
    source_lang: str = "auto",
    target_lang: str = "ru"
) -> Tuple[Optional[str], Optional[str]]:
    """Fast fallback when Google batch is unavailable or failed."""
    cache_key = f"{source_lang}:{target_lang}:{cleaned}"
    if cache_key in _translation_cache:
        return _translation_cache[cache_key]

    fast_res = _lookup_fast_dict(cleaned)
    if fast_res:
        return fast_res

    eff_sl = source_lang
    if eff_sl == "auto":
        eff_sl = detect_language_heuristic(cleaned)
    if eff_sl == "auto":
        eff_sl = "sr" if (SERBIAN_LATIN_CHARS.search(cleaned) or SERBIAN_CYRILLIC_CHARS.search(cleaned)) else "en"

    # Fallback 1: MyMemory API (fast parallel query)
    try:
        q = urllib.parse.quote(cleaned)
        mm_url = f"https://api.mymemory.translated.net/get?q={q}&langpair={eff_sl}|{target_lang}"
        mm_req = urllib.request.Request(
            mm_url,
            headers={"User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(mm_req, timeout=1.5) as mm_resp:
            mm_data = json.loads(mm_resp.read().decode("utf-8"))
            if mm_data and "responseData" in mm_data and "translatedText" in mm_data["responseData"]:
                trans = html.unescape(mm_data["responseData"]["translatedText"]).strip()
                if trans and trans.lower() != cleaned.lower() and not trans.startswith("MYMEMORY WARNING"):
                    return trans, eff_sl
    except Exception:
        pass

    # Fallback 2: local dictionary if offline
    try:
        from core.dictionary import translate_phrase_or_tokens
        local_trans = translate_phrase_or_tokens(cleaned, sl=eff_sl, tl=target_lang)
        if local_trans and local_trans.lower() != cleaned.lower():
            return local_trans, eff_sl
    except Exception:
        pass

    return cleaned, eff_sl

def _translate_single(
    cleaned: str,
    source_lang: str = "auto",
    target_lang: str = "ru"
) -> Tuple[Optional[str], Optional[str]]:
    """Single phrase translation wrapper."""
    res = batch_translate_and_detect_lang([cleaned], source_lang=source_lang, target_lang=target_lang)
    return res[0] if res else (None, None)

def translate_and_detect_lang(
    text: str,
    source_lang: str = "auto",
    target_lang: str = "ru"
) -> Tuple[Optional[str], Optional[str]]:
    """Convenience wrapper for single phrase translation."""
    res = batch_translate_and_detect_lang([text], source_lang=source_lang, target_lang=target_lang)
    return res[0] if res else (None, None)

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
        return detected_lang not in ("ru", "rus")

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
