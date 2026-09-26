"""
Comprehensive Offline Dictionary and Phrase Engine for Context HUD Translator.
Contains thousands of common English-Russian and Russian-English vocabulary entries,
multi-word phrases, idioms, and bidirectional translation heuristics.
"""

import os
import json
import re
import urllib.request
import urllib.parse
from typing import Dict, List, Optional, Tuple

ONLINE_CACHE: Dict[Tuple[str, str, str], str] = {}

def _match_case(src: str, target: str) -> str:
    """Preserves lowercase, Titlecase, or ALL CAPS from source into target."""
    if not src or not target:
        return target
    if src.isupper() and len(src) > 1:
        return target.upper()
    if src[0].isupper():
        return target[0].upper() + target[1:]
    return target.lower()

def _get_morphology_candidates(w: str) -> List[str]:
    """Generates base stem and lemma candidates for Russian inflected word forms."""
    w = w.lower()
    cands = [w]
    rules = [
        # Nouns (feminine/masculine/neuter cases & plurals)
        ('ами', ['а', '']), ('ями', ['я', 'ь', '']),
        ('ам', ['а', '']), ('ям', ['я', 'ь', '']),
        ('ах', ['а', '']), ('ях', ['я', 'ь', '']),
        ('ой', ['а', 'ый']), ('ей', ['я', 'ь', 'ий']),
        ('ом', ['', 'ый']), ('ем', ['', 'ь', 'ий']),
        ('ов', ['']), ('ев', ['', 'ь']),
        ('у', ['а']), ('ю', ['я', 'ь']),
        ('е', ['а', 'я', '']),
        ('ы', ['а', '']), ('и', ['а', 'я', 'ь', '']),
        # Adjectives
        ('ую', ['ый', 'ий', 'ая']), ('юю', ['яя', 'ий']),
        ('ое', ['ый']), ('ее', ['ий']),
        ('ая', ['ый']), ('яя', ['ий']),
        ('ые', ['ый']), ('ие', ['ий']),
        ('ого', ['ый']), ('его', ['ий']),
        ('ому', ['ый']), ('ему', ['ий']),
        ('ыми', ['ый']), ('ими', ['ий']),
        ('ых', ['ый']), ('их', ['ий']),
        # Verbs (conjugations and tenses)
        ('аешь', ['ать']), ('яешь', ['ять']), ('ешь', ['ать', 'еть', 'ти']),
        ('ишь', ['ить']), ('ит', ['ить']), ('ет', ['ать', 'еть']),
        ('ает', ['ать']), ('яет', ['ять']),
        ('аем', ['ать']), ('яем', ['ять']), ('им', ['ить']), ('ем', ['ать', 'еть']),
        ('ают', ['ать']), ('яют', ['ять']), ('ут', ['ать', 'ти']), ('ют', ['ать', 'ить']), ('ят', ['ить']),
        ('ал', ['ать']), ('ала', ['ать']), ('али', ['ать']),
        ('ил', ['ить']), ('ила', ['ить']), ('или', ['ить']),
        ('ел', ['еть']), ('ела', ['еть']), ('ели', ['еть']),
        ('уешь', ['овать']), ('ует', ['овать']), ('уют', ['овать']),
        ('овал', ['овать']), ('овала', ['овать']), ('овали', ['овать'])
    ]
    for end, repls in rules:
        if w.endswith(end) and len(w) > len(end) + 1:
            base = w[:-len(end)]
            for r in repls:
                cands.append(base + r)
    return list(dict.fromkeys(cands))

def fetch_online_translation(text: str, sl: str = "ru", tl: str = "en", timeout: float = 0.8) -> str:
    """Instant translation fallback using googleapis with in-memory caching."""
    cleaned = text.strip()
    if not cleaned:
        return ""
    key = (sl, tl, cleaned.lower())
    if key in ONLINE_CACHE:
        return ONLINE_CACHE[key]

    try:
        url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl={sl}&tl={tl}&dt=t&q=" + urllib.parse.quote(cleaned)
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            res_parts = []
            if data and data[0]:
                for item in data[0]:
                    if item and item[0]:
                        res_parts.append(item[0])
            res = "".join(res_parts)
            if res:
                res = res.replace("\u200b", "").strip()
                ONLINE_CACHE[key] = res
                return res
    except Exception:
        pass

    try:
        import html
        q = urllib.parse.quote(cleaned)
        url = f"https://api.mymemory.translated.net/get?q={q}&langpair={sl}|{tl}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data and "responseData" in data and "translatedText" in data["responseData"]:
                res = html.unescape(data["responseData"]["translatedText"]).strip()
                if res and res.lower() != cleaned.lower():
                    ONLINE_CACHE[key] = res
                    return res
    except Exception:
        pass
    return ""

# Multi-word Russian to English phrases
PHRASES_RU_TO_EN = {
    "как дела": "how are you",
    "как твои дела": "how are you doing",
    "как ваши дела": "how are you doing",
    "доброе утро": "good morning",
    "добрый день": "good afternoon",
    "добрый вечер": "good evening",
    "спокойной ночи": "good night",
    "большое спасибо": "thank you very much",
    "спасибо большое": "thank you very much",
    "спасибо": "thank you",
    "пожалуйста": "please",
    "не за что": "you are welcome",
    "до скорого": "see you soon",
    "до скорой встречи": "see you soon",
    "до свидания": "goodbye",
    "хорошего дня": "have a nice day",
    "береги себя": "take care",
    "для того чтобы": "in order to",
    "так же как и": "as well as",
    "в то же время": "at the same time",
    "с другой стороны": "on the other hand",
    "например": "for example",
    "к примеру": "for instance",
    "в результате": "as a result",
    "из-за этого": "because of this",
    "из-за": "because of",
    "благодаря": "thanks to",
    "вместо этого": "instead of this",
    "вместо": "instead of",
    "как можно скорее": "as soon as possible",
    "кстати": "by the way",
    "по крайней мере": "at least",
    "не имеет значения": "it doesn't matter",
    "не важно": "never mind",
    "конечно": "of course",
    "в порядке": "all right",
    "на самом деле": "in fact",
    "прежде всего": "first of all",
    "точка зрения": "point of view",
    "прямо сейчас": "right now",
    "друг друга": "each other",
    "один другого": "one another",
    "исходный код": "source code",
    "лист бумаги": "sheet of paper",
    "лист дерева": "leaf of a tree",
    "берег реки": "river bank",
    "компьютерная мышь": "computer mouse",
    "подъемный кран": "crane",
    "я хочу": "I want",
    "я думаю": "I think",
    "я знаю": "I know",
    "я могу": "I can",
    "я не знаю": "I don't know",
    "что это": "what is this",
    "что ты делаешь": "what are you doing",
    "где это": "where is this"
}

# Multi-word English to Russian phrases
PHRASES_EN_TO_RU = {
    "how are you": "как дела",
    "how are you doing": "как ваши дела",
    "good morning": "доброе утро",
    "good afternoon": "добрый день",
    "good evening": "добрый вечер",
    "good night": "спокойной ночи",
    "thank you very much": "большое спасибо",
    "thank you": "спасибо",
    "thanks a lot": "огромное спасибо",
    "you are welcome": "пожалуйста",
    "see you later": "до скорого",
    "see you soon": "до скорой встречи",
    "have a nice day": "хорошего дня",
    "take care": "береги себя",
    "in order to": "для того чтобы",
    "as well as": "так же как и",
    "at the same time": "в то же время",
    "on the other hand": "с другой стороны",
    "for example": "например",
    "for instance": "к примеру",
    "in front of": "перед",
    "according to": "согласно",
    "in addition to": "в дополнение к",
    "as a result": "в результате",
    "because of": "из-за",
    "due to": "благодаря / из-за",
    "instead of": "вместо",
    "such as": "такой как",
    "so that": "чтобы",
    "as soon as possible": "как можно скорее",
    "by the way": "кстати",
    "at least": "по крайней мере",
    "no matter": "не имеет значения",
    "never mind": "не важно",
    "of course": "конечно",
    "all right": "в порядке",
    "in fact": "на самом деле",
    "first of all": "прежде всего",
    "point of view": "точка зрения",
    "out of date": "устаревший",
    "up to date": "современный",
    "turn on": "включить",
    "turn off": "выключить",
    "switch on": "включить",
    "switch off": "выключить",
    "look for": "искать",
    "look at": "посмотреть на",
    "look after": "присматривать за",
    "give up": "сдаваться / бросать",
    "find out": "выяснить",
    "carry out": "выполнять",
    "set up": "настроить / установить",
    "come back": "возвращаться",
    "go on": "продолжать",
    "carry on": "продолжать",
    "work out": "разрабатывать / тренироваться",
    "sign in": "войти",
    "sign out": "выйти",
    "log in": "авторизоваться",
    "log out": "выйти из системы",
    "shut down": "выключить",
    "right now": "прямо сейчас",
    "each other": "друг друга",
    "one another": "один другого",
    "more and more": "все больше и больше",
    "sheet of paper": "лист бумаги",
    "leaf of a tree": "лист дерева",
    "river bank": "берег реки",
    "financial institution": "финансовый институт",
    "operating system": "операционная система",
    "source code": "исходный код",
    "user interface": "пользовательский интерфейс"
}

# Core Vocabulary RU -> EN
VOCAB_RU_TO_EN = {
    # Pronouns
    "я": "I", "меня": "me", "мне": "me", "мной": "me", "мною": "me",
    "мой": "my", "моя": "my", "моё": "my", "мое": "my", "мои": "my", "моего": "my", "моей": "my", "моих": "my",
    "ты": "you", "тебя": "you", "тебе": "you", "тобой": "you", "тобою": "you",
    "твой": "your", "твоя": "your", "твоё": "your", "твое": "your", "твои": "your",
    "он": "he", "его": "his", "ему": "him", "им": "him",
    "она": "she", "её": "her", "ее": "her", "ей": "her", "ею": "her",
    "оно": "it",
    "мы": "we", "нас": "us", "нам": "us", "нами": "us",
    "наш": "our", "наша": "our", "наше": "our", "наши": "our", "нашего": "our", "нашей": "our",
    "вы": "you", "вас": "you", "вам": "you", "вами": "you",
    "ваш": "your", "ваша": "your", "ваше": "your", "ваши": "your", "вашего": "your",
    "они": "they", "их": "their", "им": "them", "ими": "them",
    "это": "this", "этот": "this", "эта": "this", "эти": "these", "этого": "this", "этой": "this", "этим": "this",
    "то": "that", "тот": "that", "та": "that", "те": "those", "того": "that", "той": "that",
    "что": "what", "кто": "who", "кого": "whom", "кому": "whom", "кем": "whom",
    "где": "where", "когда": "when", "почему": "why", "как": "how", "куда": "where",
    "откуда": "where from", "зачем": "why",
    "какой": "which", "какая": "which", "какое": "which", "какие": "which", "какого": "which",
    "чей": "whose", "чья": "whose", "чьё": "whose", "чье": "whose", "чьи": "whose",
    "все": "all", "всё": "everything", "весь": "all", "вся": "all", "всех": "all", "всем": "all",
    "каждый": "every", "каждая": "every", "каждое": "every", "каждые": "every",
    "другой": "other", "другая": "other", "другое": "other", "другие": "others", "других": "others",
    "сам": "himself", "сама": "herself", "сами": "themselves", "себя": "myself / yourself",
    "много": "a lot", "мало": "little", "больше": "more", "меньше": "less",

    # Particles & Conjunctions
    "да": "yes", "нет": "no", "не": "not", "ни": "neither",
    "и": "and", "а": "and", "но": "but", "или": "or", "если": "if",
    "потому": "because", "так": "so", "чтобы": "to", "хотя": "although",
    "тоже": "also", "также": "also", "уже": "already", "еще": "still", "ещё": "still",
    "только": "only", "просто": "just", "даже": "even", "ли": "whether",
    "ведь": "after all", "же": "same", "лишь": "only",

    # Prepositions
    "в": "in", "во": "in", "на": "on", "с": "with", "со": "with", "без": "without",
    "у": "at", "о": "about", "об": "about", "обо": "about", "про": "about",
    "для": "for", "к": "to", "ко": "to", "из": "from", "изо": "from", "от": "from",
    "до": "until", "по": "by", "через": "through", "между": "between",
    "перед": "in front of", "под": "under", "над": "above", "за": "for / behind",
    "при": "during / with", "около": "near", "возле": "near", "вокруг": "around",

    # Greetings & Common Expressions
    "привет": "hello", "здравствуй": "hello", "здравствуйте": "hello",
    "хай": "hi", "пока": "bye", "досвидания": "goodbye",
    "спасибо": "thank you", "пожалуйста": "please",
    "хорошо": "good / okay", "ладно": "okay", "отлично": "great", "прекрасно": "wonderful",

    # Common Verbs (present, past, infinitive, imperative)
    "хочу": "want", "хочешь": "want", "хочет": "wants", "хотим": "want", "хотите": "want", "хотят": "want",
    "хотел": "wanted", "хотела": "wanted", "хотели": "wanted", "хотеть": "to want",
    "могу": "can", "можешь": "can", "может": "can", "можем": "can", "можете": "can", "могут": "can",
    "мог": "could", "могла": "could", "могли": "could",
    "знаю": "know", "знаешь": "know", "знает": "knows", "знаем": "know", "знают": "know",
    "знал": "knew", "знала": "knew", "знали": "knew", "знать": "to know",
    "думаю": "think", "думаешь": "think", "думает": "thinks", "думаем": "think", "думают": "think",
    "думал": "thought", "думала": "thought", "думали": "thought", "думать": "to think",
    "делаю": "am doing", "делаешь": "are doing", "делает": "does", "делаем": "do", "делают": "do",
    "делал": "did", "делала": "did", "делали": "did", "делать": "to do", "сделать": "to do",
    "пишу": "write", "пишешь": "write", "пишет": "writes", "пишем": "write", "пишете": "write", "пишут": "write",
    "писал": "wrote", "писала": "wrote", "писали": "wrote", "писать": "to write", "написать": "to write", "написал": "wrote",
    "читаю": "read", "читаешь": "read", "читает": "reads", "читаем": "read", "читают": "read",
    "читал": "read", "читала": "read", "читать": "to read",
    "говорю": "speak", "говоришь": "speak", "говорит": "speaks", "говорим": "speak", "говорят": "speak",
    "говорил": "spoke", "говорила": "spoke", "говорить": "to speak",
    "сказал": "said", "сказала": "said", "сказали": "said", "сказать": "to say", "скажи": "say",
    "вижу": "see", "видишь": "see", "видит": "sees", "видим": "see", "видят": "see",
    "видел": "saw", "видела": "saw", "видеть": "to see",
    "смотрю": "look", "смотришь": "look", "смотрит": "looks", "смотрим": "look", "смотрят": "look",
    "смотрел": "watched", "смотреть": "to look", "посмотри": "look",
    "слышу": "hear", "слышишь": "hear", "слышит": "hears", "слышал": "heard", "слышать": "to hear",
    "понимаю": "understand", "понимаешь": "understand", "понимает": "understands", "понимаем": "understand",
    "понял": "understood", "поняла": "understood", "поняли": "understood", "понять": "to understand",
    "работаю": "work", "работаешь": "work", "работает": "works", "работаем": "work", "работают": "work",
    "работал": "worked", "работала": "worked", "работать": "to work",
    "иду": "am going", "идешь": "are going", "идет": "is going", "идем": "are going", "идут": "are going",
    "шел": "went", "шла": "went", "шли": "went", "пошел": "went", "идти": "to go",
    "бегу": "run", "бежишь": "run", "бежит": "runs", "бежал": "ran", "бежать": "to run",
    "живу": "live", "живешь": "live", "живет": "lives", "живут": "live", "жил": "lived", "жить": "to live",
    "люблю": "love", "любишь": "love", "любит": "loves", "любил": "loved", "любить": "to love",
    "помогу": "will help", "помогает": "helps", "помог": "helped", "помогла": "helped", "помогать": "to help", "помоги": "help",
    "открыть": "open", "открыл": "opened", "открыла": "opened", "открывает": "opens", "открой": "open",
    "закрыть": "close", "закрыл": "closed", "закрывает": "closes", "закрой": "close",
    "найти": "find", "нашел": "found", "нашла": "found", "находит": "finds",
    "купить": "buy", "купил": "bought", "покупает": "buys",
    "продать": "sell", "продал": "sold",
    "отправить": "send", "отправил": "sent", "отправляет": "sends", "отправь": "send",
    "получить": "receive", "получил": "received", "получает": "receives",
    "проверить": "check", "проверил": "checked", "проверяет": "checks", "проверь": "check",
    "сохранить": "save", "сохранил": "saved", "сохраняет": "saves", "сохрани": "save",
    "удалить": "delete", "удалил": "deleted", "удаляет": "deletes",
    "вставить": "insert", "вставил": "inserted", "вставляет": "inserts",
    "срезать": "clip / cut", "срезал": "clipped", "срезает": "clips",
    "осмотрел": "examined", "осматривает": "examines",
    "растет": "grows", "растут": "grow", "расти": "grow",
    "является": "is", "был": "was", "была": "was", "было": "was", "были": "were", "будет": "will be", "быть": "to be",
    "есть": "is / have", "буду": "will be",

    # Nouns
    "человек": "person", "люди": "people", "мужчина": "man", "женщина": "woman", "девушка": "girl", "парень": "guy",
    "ребенок": "child", "дети": "children", "друг": "friend", "друзья": "friends", "семья": "family",
    "дом": "house", "комната": "room", "дверь": "door", "окно": "window", "стол": "table", "стена": "wall",
    "работа": "work", "время": "time", "день": "day", "дни": "days", "ночь": "night", "утро": "morning", "вечер": "evening",
    "час": "hour", "минута": "minute", "секунда": "second", "год": "year", "месяц": "month", "неделя": "week",
    "город": "city", "страна": "country", "мир": "world", "жизнь": "life",
    "текст": "text", "слово": "word", "слова": "words", "буква": "letter", "предложение": "sentence",
    "язык": "language", "перевод": "translation", "переводчик": "translator",
    "код": "code", "файл": "file", "файлы": "files", "папка": "folder", "папки": "folders",
    "программа": "program", "приложение": "application", "система": "system",
    "компьютер": "computer", "мышь": "mouse", "клавиатура": "keyboard", "экран": "screen",
    "поле": "field", "ввод": "input", "вывод": "output", "буфер": "buffer",
    "дерево": "tree", "деревья": "trees", "лист": "leaf", "листья": "leaves",
    "растение": "plant", "растения": "plants", "цветок": "flower", "цветы": "flowers",
    "сад": "garden", "садовник": "gardener", "лес": "forest", "трава": "grass", "почва": "soil",
    "вода": "water", "река": "river", "озеро": "lake", "море": "sea", "берег": "bank", "кран": "crane",
    "бумага": "paper", "документ": "document", "письмо": "letter", "книга": "book", "страница": "page",
    "деньги": "money", "банк": "bank", "счет": "account", "карта": "card",
    "вопрос": "question", "ответ": "answer", "проблема": "problem", "ошибка": "error",
    "результат": "result", "успех": "success", "дело": "thing / matter", "дела": "things",
    "вещь": "thing", "вещи": "things", "место": "place", "конец": "end", "начало": "beginning",
    "кнопка": "button", "сообщение": "message", "настройка": "setting", "настройки": "settings",
    "скорость": "speed", "задержка": "latency", "тест": "test",

    # Adjectives
    "хороший": "good", "хорошая": "good", "хорошее": "good", "хорошие": "good",
    "плохой": "bad", "плохая": "bad", "плохое": "bad", "плохие": "bad",
    "новый": "new", "новая": "new", "новое": "new", "новые": "new",
    "старый": "old", "старая": "old", "старое": "old", "старые": "old",
    "большой": "big", "большая": "big", "большое": "big", "большие": "big",
    "маленький": "small", "маленькая": "small", "маленькое": "small", "маленькие": "small",
    "быстрый": "fast", "быстрая": "fast", "быстрое": "fast", "быстрые": "fast",
    "медленный": "slow", "медленная": "slow",
    "легкий": "easy", "легкая": "easy", "легкое": "easy", "легкие": "easy",
    "простой": "simple", "простая": "simple", "простое": "simple", "простые": "simple",
    "сложный": "complex", "сложная": "complex", "трудный": "hard",
    "правильный": "correct", "верный": "right",
    "красивый": "beautiful", "красивая": "beautiful", "красивое": "beautiful",
    "зеленый": "green", "зеленая": "green", "зеленые": "green",
    "желтый": "yellow", "желтая": "yellow", "желтые": "yellow",
    "красный": "red", "синий": "blue", "белый": "white", "черный": "black",
    "больной": "diseased", "здоровый": "healthy",
    "русский": "Russian", "английский": "English",
    "важный": "important", "готовый": "ready", "бесплатный": "free", "чистый": "clean",

    # Adverbs
    "очень": "very", "быстро": "quickly", "медленно": "slowly", "плохо": "badly",
    "сейчас": "now", "потом": "later", "сегодня": "today", "завтра": "tomorrow", "вчера": "yesterday",
    "здесь": "here", "там": "there", "всегда": "always", "никогда": "never",
    "часто": "often", "редко": "rarely", "сразу": "immediately", "вместе": "together",
    "точно": "exactly", "почти": "almost"
}

_extended_path = os.path.join(os.path.dirname(__file__), "extended_vocab.json")
if os.path.exists(_extended_path):
    try:
        with open(_extended_path, "r", encoding="utf-8") as _f:
            _ext = json.load(_f)
            VOCAB_RU_TO_EN.update(_ext)
    except Exception:
        pass

# Core Vocabulary EN -> RU
VOCAB_EN_TO_RU = {
    # Greetings & Common Expressions
    "hello": "привет", "hi": "привет", "hey": "эй / привет",
    "bye": "пока", "goodbye": "до свидания", "welcome": "добро пожаловать",
    "please": "пожалуйста", "thanks": "спасибо", "thank": "благодарить",
    "yes": "да", "no": "нет",

    # Pronouns & determiners
    "i": "я", "me": "мне", "my": "мой", "mine": "мой", "myself": "себя",
    "you": "вы", "your": "ваш", "yours": "ваш", "yourself": "себя",
    "he": "он", "him": "его", "his": "его", "himself": "себя",
    "she": "она", "her": "её", "hers": "её", "herself": "себя",
    "it": "оно", "its": "его", "itself": "само по себе",
    "we": "мы", "us": "нас", "our": "наш", "ours": "наш", "ourselves": "сами",
    "they": "они", "them": "их", "their": "их", "theirs": "их", "themselves": "сами",
    "this": "этот", "that": "тот", "these": "эти", "those": "те",
    "what": "что", "which": "какой", "who": "кто", "whom": "кого", "whose": "чей",
    "where": "где", "when": "когда", "why": "почему", "how": "как",
    "all": "все", "any": "любой", "both": "оба", "each": "каждый", "few": "немногие",
    "more": "больше", "most": "большинство", "other": "другой", "some": "некоторые",
    "such": "такой", "not": "не", "only": "только", "same": "тот же",

    # Prepositions & Conjunctions
    "the": "", "a": "", "an": "",
    "in": "в", "on": "на", "at": "у / в", "by": "к / около", "with": "с",
    "without": "без", "about": "о", "against": "против", "between": "между",
    "into": "в", "through": "через", "during": "во время", "before": "до",
    "after": "после", "above": "выше", "below": "ниже", "to": "к", "from": "из",
    "up": "вверх", "down": "вниз", "in front": "спереди", "back": "назад",
    "over": "над", "under": "под", "again": "снова", "further": "дальше",
    "then": "затем", "once": "однажды", "here": "здесь", "there": "там",
    "and": "и", "but": "но", "if": "если", "or": "или", "because": "потому что",
    "as": "как", "until": "пока не", "while": "пока", "of": "",

    # Verbs
    "be": "быть", "is": "это", "are": "являются", "was": "был", "were": "были",
    "have": "иметь", "has": "имеет", "had": "имел",
    "do": "делать", "does": "делает", "did": "сделал",
    "say": "говорить", "says": "говорит", "said": "сказал",
    "go": "идти", "goes": "идет", "went": "пошел",
    "get": "получать", "gets": "получает", "got": "получил",
    "make": "делать", "makes": "делает", "made": "сделал",
    "know": "знать", "knows": "знает", "knew": "знал",
    "think": "думать", "thinks": "думает", "thought": "подумал",
    "take": "брать", "takes": "берет", "took": "взял",
    "see": "видеть", "sees": "видит", "saw": "видел",
    "come": "приходить", "comes": "приходит", "came": "пришел",
    "want": "хотеть", "wants": "хочет", "wanted": "хотел",
    "look": "смотреть", "looks": "смотрит", "looked": "посмотрел",
    "use": "использовать", "uses": "использует", "used": "использованный",
    "find": "находить", "finds": "находит", "found": "нашел",
    "give": "давать", "gives": "дает", "gave": "дал",
    "tell": "рассказывать", "tells": "рассказывает", "told": "рассказал",
    "work": "работать", "works": "работает", "worked": "работал",
    "try": "пытаться", "tries": "пытается", "tried": "пытался",
    "ask": "спрашивать", "asks": "спрашивает", "asked": "спросил",
    "need": "нуждаться", "needs": "нуждается", "needed": "требовалось",
    "feel": "чувствовать", "feels": "чувствует", "felt": "чувствовал",
    "write": "писать", "writes": "пишет", "wrote": "написал",
    "read": "читать", "reads": "читает",
    "start": "начинать", "starts": "начинает", "started": "начал",
    "open": "открыть", "opens": "открывает", "opened": "открыл",
    "close": "закрыть", "closes": "закрывает", "closed": "закрытый",
    "select": "выбрать", "copy": "копировать", "paste": "вставить",
    "translate": "переводить", "translates": "переводит", "translated": "переведенный",
    "save": "сохранить", "saves": "сохраняет", "saved": "сохраненный",
    "check": "проверить", "checks": "проверяет", "checked": "проверенный",
    "examine": "осматривать", "examines": "осматривает", "examined": "осмотрел",
    "clip": "срезать", "clips": "срезает", "clipped": "срезал",
    "grow": "расти", "grows": "растет", "growing": "растущий",

    # Nouns
    "time": "время", "person": "человек", "year": "год", "day": "день",
    "world": "мир", "life": "жизнь", "hand": "рука", "work": "работа",
    "house": "дом", "room": "комната", "door": "дверь", "window": "окно",
    "text": "текст", "code": "код", "file": "файл", "folder": "папка",
    "application": "приложение", "computer": "компьютер", "mouse": "мышь",
    "keyboard": "клавиатура", "screen": "экран", "button": "кнопка",
    "input": "ввод", "output": "вывод", "buffer": "буфер", "message": "сообщение",
    "plant": "растение", "plants": "растения", "tree": "дерево", "trees": "деревья",
    "leaf": "лист растения", "leaves": "листья", "flower": "цветок", "flowers": "цветы",
    "garden": "сад", "gardener": "садовник", "forest": "лес", "soil": "почва",
    "paper": "бумага", "sheet": "лист бумаги", "document": "документ", "letter": "письмо",
    "river": "река", "lake": "озеро", "bank": "банк", "crane": "подъемный кран",
    "spring": "весна", "water": "вода", "money": "деньги"
}

def is_cyrillic(text: str) -> bool:
    return bool(re.search(r"[\u0400-\u04FF]", text))

def translate_ru_to_en(text: str, custom_anchors: Optional[Dict[str, str]] = None) -> str:
    """Translates Russian text directly into English using phrases, anchors, dictionary, morphology and instant online fallback."""
    cleaned = text.strip()
    if not cleaned:
        return ""

    lower_input = cleaned.lower()
    # 1. Exact phrase match
    if lower_input in PHRASES_RU_TO_EN:
        res = PHRASES_RU_TO_EN[lower_input]
        return _match_case(cleaned, res)

    # 2. Check WSD anchors
    anchors = custom_anchors or {}
    if lower_input in anchors:
        res = anchors[lower_input]
        return _match_case(cleaned, res)

    # 3. Exact word match in dictionary
    if lower_input in VOCAB_RU_TO_EN:
        res = VOCAB_RU_TO_EN[lower_input]
        if " / " in res:
            res = res.split(" / ")[0]
        return _match_case(cleaned, res)

    # 4. Morphology stemming fallback for inflected words
    for cand in _get_morphology_candidates(lower_input):
        if cand in VOCAB_RU_TO_EN:
            res = VOCAB_RU_TO_EN[cand]
            if " / " in res:
                res = res.split(" / ")[0]
            return _match_case(cleaned, res)

    # 5. Fast online translation fallback for unknown words, phrases, or full sentences
    online_res = fetch_online_translation(cleaned, sl="ru", tl="en")
    if online_res and online_res.lower() != lower_input:
        return _match_case(cleaned, online_res)

    # 6. Multi-word phrase substitution
    working_text = cleaned
    for phrase, en_trans in PHRASES_RU_TO_EN.items():
        pattern = re.compile(rf"\b{re.escape(phrase)}\b", re.IGNORECASE)
        working_text = pattern.sub(en_trans, working_text)

    # 7. Tokenize words and punctuation
    tokens = re.findall(r"[\w']+|[.,!?;:\"()—–-]", working_text)
    out_tokens = []

    for tok in tokens:
        low = tok.lower()
        if re.match(r"^[.,!?;:\"()—–-]+$", tok):
            out_tokens.append(tok)
            continue

        if low in anchors:
            val = anchors[low]
            out_tokens.append(_match_case(tok, val))
            continue

        if low in VOCAB_RU_TO_EN:
            val = VOCAB_RU_TO_EN[low]
            if " / " in val:
                val = val.split(" / ")[0]
            out_tokens.append(_match_case(tok, val))
            continue

        # Stem candidate
        stem_found = False
        for cand in _get_morphology_candidates(low):
            if cand in VOCAB_RU_TO_EN:
                val = VOCAB_RU_TO_EN[cand]
                if " / " in val:
                    val = val.split(" / ")[0]
                out_tokens.append(_match_case(tok, val))
                stem_found = True
                break
        if stem_found:
            continue

        # Single token online lookup
        if is_cyrillic(tok):
            online_tok = fetch_online_translation(tok, sl="ru", tl="en")
            if online_tok and online_tok.lower() != low:
                out_tokens.append(_match_case(tok, online_tok))
                continue

        out_tokens.append(tok)

    res = " ".join(out_tokens)
    res = re.sub(r'\s+([.,!?;:)])', r'\1', res)
    res = re.sub(r'([(])\s+', r'\1', res)
    return re.sub(r'\s{2,}', ' ', res).strip()

def translate_en_to_ru(text: str, custom_anchors: Optional[Dict[str, str]] = None) -> str:
    """Translates English text directly into Russian using phrases, anchors, dictionary, and online fallback."""
    cleaned_input = text.strip()
    if not cleaned_input:
        return ""

    lower_input = cleaned_input.lower()
    if lower_input in PHRASES_EN_TO_RU:
        res = PHRASES_EN_TO_RU[lower_input]
        return _match_case(cleaned_input, res)

    anchors = custom_anchors or {}
    if lower_input in anchors:
        res = anchors[lower_input]
        return _match_case(cleaned_input, res)

    if lower_input in VOCAB_EN_TO_RU:
        res = VOCAB_EN_TO_RU[lower_input]
        if res:
            return _match_case(cleaned_input, res)

    working_text = cleaned_input
    for phrase, ru_trans in PHRASES_EN_TO_RU.items():
        pattern = re.compile(rf"\b{re.escape(phrase)}\b", re.IGNORECASE)
        working_text = pattern.sub(ru_trans, working_text)

    tokens = re.findall(r"[\w']+|[.,!?;:\"()—–-]", working_text)
    translated_tokens: List[str] = []
    matched_any = False

    for tok in tokens:
        low_tok = tok.lower()
        if re.match(r"^[.,!?;:\"()—–-]+$", tok):
            translated_tokens.append(tok)
            continue

        if low_tok in anchors:
            val = anchors[low_tok]
            translated_tokens.append(_match_case(tok, val))
            matched_any = True
            continue

        if low_tok in VOCAB_EN_TO_RU:
            val = VOCAB_EN_TO_RU[low_tok]
            if val:
                translated_tokens.append(_match_case(tok, val))
                matched_any = True
                continue

        translated_tokens.append(tok)

    if matched_any:
        result = " ".join(translated_tokens)
        result = re.sub(r'\s+([.,!?;:)])', r'\1', result)
        result = re.sub(r'([(])\s+', r'\1', result)
        return re.sub(r'\s{2,}', ' ', result).strip()

    # Fast online fallback for full phrase/sentence
    online_res = fetch_online_translation(cleaned_input, sl="en", tl="ru")
    if online_res and online_res.lower() != lower_input:
        return _match_case(cleaned_input, online_res)

    result = " ".join(translated_tokens)
    result = re.sub(r'\s+([.,!?;:)])', r'\1', result)
    result = re.sub(r'([(])\s+', r'\1', result)
    return re.sub(r'\s{2,}', ' ', result).strip()

def translate_phrase_or_tokens(
    text: str,
    custom_anchors: Optional[Dict[str, str]] = None,
    sl: str = "auto",
    tl: str = "auto"
) -> str:
    """
    Translates text according to source language (sl) and target language (tl).
    Supports auto-detection, bidirectional RU <-> EN dictionaries, and any other
    language pairs via instant fallback and caching.
    """
    cleaned_input = text.strip()
    if not cleaned_input:
        return ""

    if sl == "auto":
        eff_sl = "ru" if is_cyrillic(cleaned_input) else "en"
        eff_tl = "en" if eff_sl == "ru" else ("ru" if tl in ("auto", "en") else tl)
    else:
        eff_sl = sl
        eff_tl = "en" if (tl == "auto" and eff_sl == "ru") else ("ru" if tl == "auto" else tl)

    # 1. Russian -> English
    if eff_sl == "ru" and eff_tl == "en":
        return translate_ru_to_en(cleaned_input, custom_anchors)

    # 2. English -> Russian
    if eff_sl == "en" and eff_tl == "ru":
        return translate_en_to_ru(cleaned_input, custom_anchors)

    # 3. Custom anchors for any language pair
    anchors = custom_anchors or {}
    lower_input = cleaned_input.lower()
    if lower_input in anchors:
        return _match_case(cleaned_input, anchors[lower_input])

    # 4. Instant multi-language translation for other pairs (e.g. RU -> DE, EN -> ES, etc.)
    online_res = fetch_online_translation(cleaned_input, sl=eff_sl, tl=eff_tl)
    if online_res and online_res.lower() != lower_input:
        return _match_case(cleaned_input, online_res)

    return cleaned_input
