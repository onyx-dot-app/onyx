# These prompts are to support tool calling. Currently not used in the main flow or via any configs
# The current generation of LLM is too unreliable for this task.
# Onyx retrieval call as a tool option
DANSWER_TOOL_NAME = "Текущий поиск"
DANSWER_TOOL_DESCRIPTION = (
    "Инструмент поиска, с помощью которого можно найти информацию по любой теме "
    "включая актуальные и защищенные авторскими правами сведения."
)


# Tool calling format inspired from LangChain
TOOL_TEMPLATE = """
ИНСТРУМЕНТЫ
------
Можешь использовать инструменты для поиска информации, которая может быть полезна при ответе на \
исходный вопрос пользователя. Доступны следующие инструменты:

{tool_overviews}

ИНСТРУКЦИИ ПО ФОРМАТУ ОТВЕТА
----------------------------
Отвечая мне, пожалуйста, выводи ответ в одном из двух форматов:

**Вариант #1:**
Используй этот вариант, если хочешь использовать инструмент. Фрагмент кода Markdown, отформатированный по следующей схеме:

```json
{{
    "action": string, \\ Какие действия необходимо предпринять. {tool_names}
    "action_input": string \\ Входные данные для выполнения действия
}}
```

**Вариант #2:**
Используйте его, если вы хочешь напрямую ответить пользователю. Фрагмент кода Markdown, отформатированный по следующей схеме:

```json
{{
    "action": "Окончательный ответ",
    "action_input": string \\ Тебе следует поместить сюда то, что ты хочешь вернуть для использования
}}
```
"""

# For the case where the user has not configured any tools to call, but still using the tool-flow
# expected format
TOOL_LESS_PROMPT = """
Ответь фрагментом кода markdown по следующей схеме:

```json
{{
    "action": "Окончательный ответ",
    "action_input": string \\ Тебе следует поместить сюда то, что ты хочешь вернуть для использования
}}
```
"""


# Second part of the prompt to include the user query
USER_INPUT = """
ВВОД ДАННЫХ ПОЛЬЗОВАТЕЛЕМ
--------------------
Вот вводимые пользователем данные \
(не забудьте ответить фрагментом кода markdown в виде большого двоичного объекта в формате json одним действием и ничем больше):

{user_input}
"""


# After the tool call, this is the following message to get a final answer
# Tools are not chained currently, the system must provide an answer after calling a tool
TOOL_FOLLOWUP = """
ИНСТРУМЕНТ ДЛЯ ОТВЕТА:
---------------------
{tool_output}

ВВОД ДАННЫХ ПОЛЬЗОВАТЕЛЕМ
--------------------
Итак, каков ответ на мой последний комментарий? Если ты используешь информацию, полученную из инструментов,\
укажи ее явно, не упоминая названия инструментов - я забыл все ОТВЕТЫ ИНСТРУМЕНТОВ!
Если ответ инструмента бесполезен, полностью игнорируй его.
{optional_reminder}{hint}
ВАЖНО! Тебе НЕОБХОДИМО ответить фрагментом кода markdown большого двоичного объекта json одним действием, и ничем больше.
"""


# If no tools were used, but retrieval is enabled, then follow up with this message to get the final answer
TOOL_LESS_FOLLOWUP = """
При ответе на мой последний запрос обратись к следующим контекстным документам. Игнорируй все документы, которые не имеют отношения к делу.

КОНТЕКСТНЫЕ ДОКУМЕНТЫ:
---------------------
{context_str}

ОКОНЧАТЕЛЬНЫЙ ЗАПРОС:
--------------------
{user_query}

{hint_text}
"""
