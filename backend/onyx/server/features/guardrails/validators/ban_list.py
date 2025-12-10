import re

from onyx.utils.logger import setup_logger

logger = setup_logger()


def levenshtein_distance(s1: str, s2: str) -> int:
    """Вычисляет расстояние Левенштейна между двумя строками.

    Пример вычисления расстояние Ливенштейна

    Операции для превращения "красиво" в "красивый":
    - к р а с и в о   (7 символов)
    - к р а с и в ы й (8 символов)

    Расчет:
    - Совпадают: к-к, р-р, а-а, с-с, и-и, в-в (6 операций по 0)
    - Замена: о → ы (1 операция)
    - Добавление: й (1 операция)

    Итого: 1 замена + 1 добавление = расстояние 2
    """
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)

    previous_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row

    return previous_row[-1]


def get_masked_replacement(word: str) -> str:
    """
    Возвращает маскированную версию слова, сохраняя начало и конец
    в зависимости от длины слова.
    """
    return "*****"

    # На случай, если необходимо закрывать слова не полностью,
    # а оставлять по краям по 1-2 букквы.
    # length = len(word)
    #
    # if length <= 2:
    #     # Очень короткие слова закрываем полностью
    #     return '*' * length
    # elif length == 3:
    #     # Три буквы: "Бля" -> "Б**"
    #     return word[0] + '*' * (length - 1)
    # elif length <= 5:
    #     # 4-5 букв: "Урод" -> "У**д", "Дурак" -> "Д***к"
    #     # Оставляем 1 букву с краев
    #     return word[0] + '*' * (length - 2) + word[-1]
    # else:
    #     # 6+ букв: "Идиотский" -> "Ид*****ий"
    #     # Адаптивно: если длина > 7, оставляем 2, иначе 1.
    #     prefix_len = 2 if length > 7 else 1
    #     suffix_len = 2 if length > 7 else 1
    #
    #     return word[:prefix_len] + '*' * (length - prefix_len - suffix_len) + word[-suffix_len:]


def mask_banned_words(
    text: str,
    banned_words: list[str],
    max_l_dist: int,
) -> str:
    """Маскирует запрещенные слова в тексте, заменяя их на звездочки.

    Функция ищет целые слова, которые совпадают с запрещенными словами
    с учетом максимального расстояния Левенштейна. Это позволяет находить
    слова с опечатками и различными формами, но не маскирует части слов.
    """
    if not text or not banned_words:
        return text

    # Приводим запрещенные слова к нижнему регистру для сравнения
    banned_words_lower = [word.lower() for word in banned_words]

    # Регулярное выражение для поиска слов (буквы русского и английского алфавитов)
    pattern = re.compile(r'[a-zA-Zа-яА-Я]+')

    # Находим все слова в тексте
    matches = list(pattern.finditer(text))

    # Собираем замены с конца текста к началу, чтобы не сбивать позиции
    replacements = []

    for match in matches:
        original_word = match.group()
        word_lower = original_word.lower()

        for banned_word in banned_words_lower:
            # Быстрая проверка на точное совпадение
            if word_lower == banned_word:
                start, end = match.span()
                replacement = get_masked_replacement(original_word)
                replacements.append((start, end, replacement))
                break

            # Проверяем на вхождение корня (startswith)
            # Если слово начинается с запрещенного (и оно >= 3 символов), считаем это матом
            if len(banned_word) >= 3 and word_lower.startswith(banned_word):
                start, end = match.span()
                replacement = get_masked_replacement(original_word)
                replacements.append((start, end, replacement))
                break

            # Адаптивный порог расстояния Левенштейна
            # Для коротких слов (<= 3 символов) разрешаем максимум 0 ошибок (только точное совпадение)
            # Для слов средней длины (4-5 символов) разрешаем максимум 1 ошибку
            # Для длинных слов (> 5 символов) используем переданный max_l_dist (обычно 2)
            current_max_dist = max_l_dist
            banned_len = len(banned_word)

            if banned_len <= 3:
                current_max_dist = 0
            elif banned_len <= 5:
                current_max_dist = min(1, max_l_dist)

            # Проверяем разницу в длине с учетом адаптивного порога
            if abs(len(word_lower) - banned_len) > current_max_dist:
                continue

            # Вычисляем расстояние Левенштейна только если имеет смысл
            if current_max_dist > 0:
                distance = levenshtein_distance(word_lower, banned_word)
                if distance <= current_max_dist:
                    # print(word_lower, banned_word)
                    start, end = match.span()
                    replacement = get_masked_replacement(original_word)
                    replacements.append((start, end, replacement))
                    break

    # Применяем замены с конца текста к началу
    for start, end, replacement in sorted(replacements, reverse=True):
        text = text[:start] + replacement + text[end:]

    return text


def validate_banned_words(
    text: str,
    config: dict,
    max_l_dist: int = 2
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
            "Ошибка при маскировании запрещенных слов: %s", repr(e)
        )
        return text
