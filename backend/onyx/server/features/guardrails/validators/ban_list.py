from fuzzysearch import find_near_matches

from onyx.utils.logger import setup_logger

logger = setup_logger()


def mask_banned_words(
    text: str, banned_words: list[str], max_l_dist: int
) -> str:
    """Маскирует запрещенные слова в тексте, заменяя их на звездочки.

    Функция использует нечеткий поиск (расстояние Левенштейна) для обнаружения
    запрещенных слов с учетом возможных опечаток, морфологических вариаций
    и небольших искажений. Расстояние Левенштейна показывает минимальное
    количество операций (добавление, удаление, замена символов) для превращения
    одной строки в другую.

    Поиск осуществляется без учета пробелов и регистра, что позволяет находить
    слова в различных форматах написания. Каждое найденное совпадение заменяется
    на последовательность звездочек, сохраняя оригинальную длину слова для
    читаемости структуры текста.

    Параметр max_l_dist определяет максимально допустимое расстояние Левенштейна
    для нечеткого поиска (по умолчанию 1 операция).
    """
    spaceless_value = text.replace(" ", "").lower()

    spaceless_index_map = []

    actual_index = 0
    for i in range(len(text)):
        actual_index += 1
        if text[i] != " ":
            spaceless_index_map.append((text[i], actual_index))

    all_matches = []
    for banned_word in banned_words:
        spaceless_banned_word = banned_word.replace(" ", "").lower()
        if not spaceless_banned_word:
            continue
        matches = find_near_matches(spaceless_banned_word, spaceless_value, max_l_dist=max_l_dist)
        all_matches.extend(matches)

    if len(all_matches) > 0:
        fix_value = text
        for match in all_matches:
            actual_start = spaceless_index_map[match.start][1]
            actual_end = spaceless_index_map[match.end - 1][1]
            triggering_text = text[actual_start:actual_end]

            replacement = "*" * len(triggering_text)
            fix_value = fix_value.replace(triggering_text, replacement)

        return fix_value

    return text


def validate_banned_words(
    text: str, config: dict, max_l_dist: int = 1
) -> str:
    """Проверяет текст на наличие запрещенных слов и маскирует их при обнаружении.

    Основная функция-обертка для цензурирования текста. Извлекает список
    запрещенных слов из конфигурации и передает их в функцию маскирования.
    Обрабатывает ошибки и возвращает исходный текст в случае проблем с обработкой.
    Используется для фильтрации нежелательного контента в ответах от LLM.
    """

    banned_words = config.get("banned_words")

    if not banned_words:
        return text

    try:
        masked_text = mask_banned_words(
            text=text,
            banned_words=banned_words,
            max_l_dist=max_l_dist,
        )
        return masked_text
    except Exception as e:
        logger.error(
            "Ошибка при анализе стиля ответа LLM: %s", repr(e)
        )
        return text
