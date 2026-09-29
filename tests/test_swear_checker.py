import pytest

from bad_words_list import EXACT_WORDS, NEUTRAL_WORDS, ROOT_WORDS
from services import check_text_for_swears, check_text_for_swears_detailed


def contains_bad_word(text: str) -> bool:
    count, _ = check_text_for_swears(text)
    return count > 0


def test_clean_text():
    assert not contains_bad_word("Привет! Как твои дела сегодня?")


@pytest.mark.parametrize(
    "text,count",
    [
        ("привет,с.у.к.а", 1),
        ("сука,п-и-д-о-р", 2),
        ("с.у.к.а,п-и-д-о-р", 2),
        ("привет.с.у.к.а", 1),
        ("с.у.к.а!п-и-д-о-р", 2),
        ("п-и-д-о-р.с.у.к.а", 2),
    ],
)
def test_obfuscated_words_next_to_punctuation(text, count):
    assert check_text_for_swears(text)[0] == count


@pytest.mark.parametrize(
    "text",
    [
        "долбить стену",
        "долбануть молотком",
        "долбим стену",
        "хачапури",
        "требуется учеба",
        "подсвинтили винтик",
        "свинцовые гири",
    ],
)
def test_safe_words_do_not_match_broad_roots(text):
    result = check_text_for_swears_detailed(text)
    assert result.swear_count == result.neutral_count == 0


def test_chat_vocabulary_categories():
    result = check_text_for_swears_detailed("мудло мрази гондоны ёбнутый подсвинок свинтус")
    assert result.swear_count == 4
    assert result.neutral_words == ["подсвинок", "свинтус"]


def test_exact_bad_word():
    assert contains_bad_word("Ну ты и сука")


def test_neutral_word_is_detected_separately():
    result = check_text_for_swears_detailed("Ну ты и чмо")

    assert result.swear_count == 0
    assert result.swear_words == []
    assert result.neutral_count == 1
    assert result.neutral_words == ["чмо"]


def test_uppercase_bad_word():
    assert contains_bad_word("ПИДОР, что ты натворил?")


def test_hidden_bad_word():
    assert contains_bad_word("с.у.к.а")
    assert contains_bad_word("п-и-д-о-р")


def test_false_positive():
    assert not contains_bad_word("Он начал громко чмокать губами")
    assert not contains_bad_word("Сукно лежит на столе")
    assert not contains_bad_word("Херсон сегодня солнечный")


def test_punctuation_around():
    assert contains_bad_word("Слушай,сука,хватит")


def test_exact_phrase():
    result = check_text_for_swears_detailed("Ну это голем пучеглазый")

    assert result.swear_count == 0
    assert result.neutral_count == 1
    assert result.neutral_words == ["голем пучеглазый"]


@pytest.mark.parametrize("word", EXACT_WORDS)
def test_all_exact_words_are_detected(word):
    count, found_words = check_text_for_swears(f"ну {word} тут")

    assert count >= 1
    assert word in found_words


@pytest.mark.parametrize("word", NEUTRAL_WORDS)
def test_all_neutral_words_are_detected(word):
    result = check_text_for_swears_detailed(f"ну {word} тут")

    assert result.neutral_count >= 1
    assert word in result.neutral_words


@pytest.mark.parametrize("root", ROOT_WORDS)
def test_all_roots_are_detected(root):
    word = f"{root}овый"

    count, found_words = check_text_for_swears(f"ну {word} тут")

    assert count == 1
    assert found_words == [word]


def test_counts_multiple_swears_in_one_message():
    result = check_text_for_swears_detailed("сука, какой-то дебил и п-и-д-о-р")

    assert result.swear_count == 2
    assert result.swear_words == ["сука", "пидор"]
    assert result.neutral_count == 1
    assert result.neutral_words == ["дебил"]


def test_duplicate_letters_are_normalized():
    count, found_words = check_text_for_swears("суууука")

    assert count == 1
    assert found_words == ["сука"]


def test_leetspeak_is_normalized():
    count, found_words = check_text_for_swears("cyk@")

    assert count == 1
    assert found_words == ["сука"]


def test_word_lists_have_no_duplicates():
    assert len(ROOT_WORDS) == len(set(ROOT_WORDS))
    assert len(EXACT_WORDS) == len(set(EXACT_WORDS))
    assert len(NEUTRAL_WORDS) == len(set(NEUTRAL_WORDS))


def test_word_lists_do_not_overlap():
    assert set(EXACT_WORDS).isdisjoint(NEUTRAL_WORDS)


def test_exact_words_do_not_duplicate_root_coverage():
    covered_exact_words = [
        word
        for word in EXACT_WORDS
        if " " not in word and any(word.startswith(root) for root in ROOT_WORDS)
    ]

    assert covered_exact_words == []


def test_empty_text_is_clean():
    assert check_text_for_swears("") == (0, [])
    assert check_text_for_swears("   ") == (0, [])


def test_exact_phrase_with_extra_spaces_is_detected_once():
    result = check_text_for_swears_detailed("это голем     пучеглазый сегодня")

    assert result.swear_count == 0
    assert result.neutral_count == 1
    assert result.neutral_words == ["голем     пучеглазый"]


def test_exact_phrase_does_not_double_count_inner_words():
    count, found_words = check_text_for_swears("хуесос кальянщик")

    assert count == 1
    assert found_words == ["хуесос кальянщик"]


def test_exact_phrase_requires_word_boundaries():
    assert check_text_for_swears("големпучеглазый") == (0, [])


def test_mixed_phrase_exact_word_and_root_count_together():
    result = check_text_for_swears_detailed("голем пучеглазый, сука, разьебал")

    assert result.swear_count == 2
    assert result.swear_words == ["сука", "разьебал"]
    assert result.neutral_count == 1
    assert result.neutral_words == ["голем пучеглазый"]


def test_obfuscated_word_with_symbols_counts_once():
    count, found_words = check_text_for_swears("п.и.з.д.е.ц")

    assert count == 1
    assert found_words == ["пиздец"]


@pytest.mark.parametrize("text", ["пи-здец", "пиз-дец", "пи\u200bздец", "с\u200bука"])
def test_single_symbol_insertion_does_not_bypass_filter(text):
    assert contains_bad_word(text)


def test_punctuation_between_regular_words_does_not_double_count():
    result = check_text_for_swears_detailed("пиздец,херня")

    assert result.swear_count == 1
    assert result.swear_words == ["пиздец"]
    assert result.neutral_count == 1
    assert result.neutral_words == ["херня"]


def test_normal_word_containing_exact_word_is_not_detected():
    assert check_text_for_swears("сукинсын") == (0, [])


def test_leetspeak_with_uppercase_is_normalized():
    count, found_words = check_text_for_swears("CYK@")

    assert count == 1
    assert found_words == ["сука"]


def test_duplicate_letters_in_root_word_are_normalized():
    count, found_words = check_text_for_swears("пииииздец")

    assert count == 1
    assert found_words == ["пиздец"]


def test_multiple_occurrences_of_same_swear_are_counted():
    count, found_words = check_text_for_swears("сука сука")

    assert count == 2
    assert found_words == ["сука", "сука"]


def test_exact_phrase_across_newline_is_detected():
    result = check_text_for_swears_detailed("голем\nпучеглазый")

    assert result.swear_count == 0
    assert result.neutral_count == 1
    assert result.neutral_words == ["голем\nпучеглазый"]


def test_exact_phrase_with_punctuation_boundaries_is_detected():
    result = check_text_for_swears_detailed("(голем пучеглазый)!")

    assert result.swear_count == 0
    assert result.neutral_count == 1
    assert result.neutral_words == ["голем пучеглазый"]


def test_phrase_match_does_not_remove_neighboring_swears():
    result = check_text_for_swears_detailed("сука голем пучеглазый херня")

    assert result.swear_count == 1
    assert result.swear_words == ["сука"]
    assert result.neutral_count == 2
    assert result.neutral_words == ["голем пучеглазый", "херня"]


def test_legal_double_letters_are_not_over_normalized():
    result = check_text_for_swears_detailed("ссанина и фаллос")

    assert result.swear_count == 1
    assert result.swear_words == ["ссанина"]
    assert result.neutral_count == 1
    assert result.neutral_words == ["фаллос"]


def test_leetspeak_digits_are_normalized():
    count, found_words = check_text_for_swears("xyeBo")

    assert count == 1
    assert found_words == ["хуево"]


def test_obfuscated_exact_word_with_underscores_is_detected():
    count, found_words = check_text_for_swears("с_у_к_а")

    assert count == 1
    assert found_words == ["сука"]


def test_obfuscated_two_letter_word_is_not_detected_by_symbol_joiner():
    assert check_text_for_swears("л-о") == (0, [])


def test_numbers_do_not_create_false_positive():
    assert check_text_for_swears("номер 1304") == (0, [])


def test_very_long_root_match_is_safely_limited_for_storage():
    count, found_words = check_text_for_swears("пизд" + "аб" * 250)

    assert count == 1
    assert len(found_words[0]) == 100


def test_exact_phrase_with_long_whitespace_is_safely_limited_for_storage():
    result = check_text_for_swears_detailed("голем" + " " * 500 + "пучеглазый")

    assert result.neutral_count == 1
    assert len(result.neutral_words[0]) == 100
