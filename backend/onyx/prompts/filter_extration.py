# The following prompts are used for extracting filters to apply along with the query in the
# document index. For example, a filter for dates or a filter by source type such as GitHub
# or Slack
from onyx.prompts.constants import SOURCES_KEY


# Smaller followup prompts in time_filter.py
TIME_FILTER_PROMPT = """
Ты являешься инструментом для определения временных фильтров, которые будут применяться к пользовательскому запросу для последующего поиска в \
приложении. Последующее приложение может использовать смещение по времени или применить жесткое ограничение, чтобы \
удалить все документы до окончания срока действия. Определи правильные фильтры для применения к пользовательскому запросу.

Текущий день и время - {current_day_time_str}.

Всегда отвечай только с помощью json, который содержит ключи "filter_type", "filter_value", \
"value_multiple" и "date".

Допустимыми значениями для "filter_type" являются "hard cutoff", "favors recent", или "not time sensitive".
Допустимыми значениями для "filter_value" являются "day", "week", "month", "quarter", "half", или "year".
Допустимыми значениями для "value_multiple" это некоторое число.
Допустимыми значениями для "date" это дата в формате MM/DD/YYYY, всегда следуйте этому формату.
""".strip()


# Smaller followup prompts in source_filter.py
# Known issue: LLMs like GPT-3.5 try to generalize. If the valid sources contains "web" but not
# "confluence" and the user asks for confluence related things, the LLM will select "web" since
# confluence is accessed as a website. This cannot be fixed without also reducing the capability
# to match things like repository->github, website->web, etc.
# This is generally not a big issue though as if the company has confluence, hopefully they add
# a connector for it or the user is aware that confluence has not been added.
SOURCE_FILTER_PROMPT = f"""
По запросу пользователя извлеки соответствующие исходные фильтры для использования в последующем поисковом инструменте.
В ответ укажи json-файл, содержащий исходные фильтры, или значение null, если ссылки на конкретные источники отсутствуют.
Извлекай источники только в том случае, если пользователь явно ограничивает область получения информации.

Пользователь может указать недопустимые исходные фильтры, игнорируй их.

Действительными источниками являются:
{{valid_sources}}
{{web_source_warning}}
{{file_source_warning}}


ВСЕГДА отвечай, используя ТОЛЬКО json с ключом "{SOURCES_KEY}". \
Значение для "{SOURCES_KEY}" должно быть нулевым или содержать список допустимых источников.

Примерный ответ:
{{sample_response}}
""".strip()

WEB_SOURCE_WARNING = """
Примечание: "веб-источник" применяется только в том случае, если пользователь указывает "вебсайт" в запросе. \
Это не относится к таким инструментам, как Confluence, GitHub и т.д., у которых есть веб-сайт.
""".strip()

FILE_SOURCE_WARNING = """
Примечание: Источник "файл" применяется только в том случае, когда пользователь ссылается в запросе на загруженные файлы.
""".strip()


# Use the following for easy viewing of prompts
if __name__ == "__main__":
    print(TIME_FILTER_PROMPT)
    print("------------------")
    print(SOURCE_FILTER_PROMPT)
