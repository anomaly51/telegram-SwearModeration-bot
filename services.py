import re
from dataclasses import dataclass

from bad_words_list import EXACT_WORDS, LEETSPEAK_MAP, NEUTRAL_WORDS, ROOT_WORDS


WORD_PATTERN = re.compile(r"[а-яёa-z0-9]+")
DUPLICATE_PATTERN = re.compile(r"(.)\1+")
# Commas and sentence punctuation delimit separate words; inner dots/dashes join letters.
OBFUSCATED_WORD_PATTERN = re.compile(r"[а-яёa-z0-9]+(?:[._*\-\u200b\u200c\u200d]+[а-яёa-z0-9]+)+")
MAX_RECORDED_WORD_LENGTH = 100


@dataclass(frozen=True)
class SwearCheckResult:
    swear_count: int
    swear_words: list[str]
    neutral_count: int
    neutral_words: list[str]


def _compile_phrase_patterns(words: tuple[str, ...]) -> tuple[re.Pattern, ...]:
    return tuple(
        re.compile(
            rf"(?<![а-яёa-z0-9]){r'\s+'.join(map(re.escape, phrase.split()))}"
            rf"(?![а-яёa-z0-9])"
        )
        for phrase in words
        if " " in phrase
    )


EXACT_WORDS_SET = {word for word in EXACT_WORDS if " " not in word}
NEUTRAL_WORDS_SET = {word for word in NEUTRAL_WORDS if " " not in word}
EXACT_WORD_ALIASES = {
    word.translate(LEETSPEAK_MAP): word
    for word in EXACT_WORDS_SET
    if word.translate(LEETSPEAK_MAP) != word
}
NEUTRAL_WORD_ALIASES = {
    word.translate(LEETSPEAK_MAP): word
    for word in NEUTRAL_WORDS_SET
    if word.translate(LEETSPEAK_MAP) != word
}
EXACT_PHRASE_PATTERNS = _compile_phrase_patterns(EXACT_WORDS)
NEUTRAL_PHRASE_PATTERNS = _compile_phrase_patterns(NEUTRAL_WORDS)


def _normalize_word(word: str) -> str:
    return DUPLICATE_PATTERN.sub(r"\1", word)


def _is_bad_word(word: str) -> bool:
    if word in EXACT_WORDS_SET:
        return True

    for root in ROOT_WORDS:
        if not word.startswith(root):
            continue

        return True

    return False


def _find_word(
    word: str,
    *,
    exact_words: set[str],
    aliases: dict[str, str],
    include_roots: bool = False,
) -> str | None:
    if word in aliases:
        return aliases[word]

    if word in exact_words:
        return word

    if include_roots and _is_bad_word(word):
        return word

    normalized_word = _normalize_word(word)
    if normalized_word in aliases:
        return aliases[normalized_word]

    if normalized_word in exact_words:
        return normalized_word

    if include_roots and normalized_word != word and _is_bad_word(normalized_word):
        return normalized_word

    return None


def _limit_recorded_word(word: str) -> str:
    return word[:MAX_RECORDED_WORD_LENGTH]


def _classify_word(word: str) -> tuple[str | None, str | None]:
    swear_word = _find_word(
        word,
        exact_words=EXACT_WORDS_SET,
        aliases=EXACT_WORD_ALIASES,
        include_roots=True,
    )
    if swear_word:
        return swear_word, None

    neutral_word = _find_word(
        word,
        exact_words=NEUTRAL_WORDS_SET,
        aliases=NEUTRAL_WORD_ALIASES,
    )
    return None, neutral_word


def _append_classified_word(word: str, swear_words: list[str], neutral_words: list[str]) -> None:
    swear_word, neutral_word = _classify_word(word)
    if swear_word:
        swear_words.append(_limit_recorded_word(swear_word))
    elif neutral_word:
        neutral_words.append(_limit_recorded_word(neutral_word))


def _obfuscated_word_choices(parts, classification_cache):
    recognized = [any(_classify_word(part)) for part in parts]
    # Prefer multiple complete words over a single over-broad root match.
    scores = [(0, 0)] * (len(parts) + 1)
    choices = {}
    for start in range(len(parts) - 1, -1, -1):
        scores[start] = scores[start + 1]
        joined = ""
        for end in range(start, min(len(parts), start + 64)):
            if recognized[end]:
                break
            joined += parts[end]
            if end == start:
                continue
            if joined not in classification_cache:
                classification_cache[joined] = _classify_word(joined)
            found = classification_cache[joined]
            if not any(found):
                continue
            score = (scores[end + 1][0] + 1, scores[end + 1][1] + len(joined))
            if score > scores[start]:
                scores[start] = score
                choices[start] = (end + 1, found)
    return choices


def _append_obfuscated_words(text, swear_words, neutral_words):
    classification_cache = {}
    for match in OBFUSCATED_WORD_PATTERN.finditer(text):
        parts = WORD_PATTERN.findall(match.group(0))
        choices = _obfuscated_word_choices(parts, classification_cache)
        index = 0
        while index < len(parts):
            if index not in choices:
                index += 1
                continue
            index, (swear, neutral) = choices[index]
            if swear:
                swear_words.append(_limit_recorded_word(swear))
            elif neutral:
                neutral_words.append(_limit_recorded_word(neutral))


def check_text_for_swears_detailed(text: str) -> SwearCheckResult:
    if not text:
        return SwearCheckResult(0, [], 0, [])

    text = text.lower().translate(LEETSPEAK_MAP)

    swear_phrase_matches = []
    for pattern in EXACT_PHRASE_PATTERNS:
        swear_phrase_matches.extend(match.group(0) for match in pattern.finditer(text))
        text = pattern.sub(" ", text)

    neutral_phrase_matches = []
    for pattern in NEUTRAL_PHRASE_PATTERNS:
        neutral_phrase_matches.extend(match.group(0) for match in pattern.finditer(text))
        text = pattern.sub(" ", text)

    words = WORD_PATTERN.findall(text)

    swear_words = []
    neutral_words = []

    swear_words.extend(_limit_recorded_word(word) for word in swear_phrase_matches)
    neutral_words.extend(_limit_recorded_word(word) for word in neutral_phrase_matches)

    for word in words:
        _append_classified_word(word, swear_words, neutral_words)

    _append_obfuscated_words(text, swear_words, neutral_words)

    return SwearCheckResult(
        swear_count=len(swear_words),
        swear_words=swear_words,
        neutral_count=len(neutral_words),
        neutral_words=neutral_words,
    )


def check_text_for_swears(text: str) -> tuple[int, list[str]]:
    result = check_text_for_swears_detailed(text)

    return result.swear_count, result.swear_words
