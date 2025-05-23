# The following prompts are used for verifying if the user's query can be answered by the current
# system. Many new users do not understand the design/capabilities of the system and will ask
# questions that are unanswerable such as aggregations or user specific questions that the system
# cannot handle, this is used to identify those cases
from onyx.prompts.constants import ANSWERABLE_PAT
from onyx.prompts.constants import GENERAL_SEP_PAT
from onyx.prompts.constants import QUESTION_PAT
from onyx.prompts.constants import THOUGHT_PAT


ANSWERABLE_PROMPT = f"""
ТЫ являешься вспомогательным инструментом для определения соответствия запроса с помощью расширенной генерации результатов поиска.
Основная система попытается ответить на запрос пользователя, основываясь только на 5 наиболее релевантных \
документах, найденных в результате поиска.
Источники содержат как актуальную, так и конфиденциальную информацию для конкретной команды.
Что касается именованных или неизвестных объектов, предположи, что поиск приведет к определению соответствующих и непротиворечивых сведений \
об объекте.
Система не настроена для написания кода.
Система не настроена для взаимодействия со структурированными данными с помощью языков запросов, таких как SQL.
Если вопрос может не требовать использования кода или языка запроса, то предположи, что на него можно ответить без использования \
кода или языка запроса.
Определи, должна ли система пытаться ответить.
"ANSWERABLE" должен быть точно равен "True" или "False".

{GENERAL_SEP_PAT}

{QUESTION_PAT.upper()} О чем этот Slack канал?
```
{THOUGHT_PAT.upper()} Сначала система должна определить, к какому каналу Slack относится сообщение. \
Выбрав 5 документов, относящихся к содержимому канала Slack, невозможно определить, какой это \
канал Slack, на который ссылается пользователь.
{ANSWERABLE_PAT.upper()} False
```

{QUESTION_PAT.upper()} Onyx недоступен.
```
{THOUGHT_PAT.upper()} Система выполняет поиск документов, связанных с недоступностью Onyx. \
Предполагая, что документы из поиска содержат ситуации, в которых Onyx недоступен, и \
содержат исправление, запрос может быть удовлетворительным.
{ANSWERABLE_PAT.upper()} True
```

{QUESTION_PAT.upper()} Сколько у нас клиентов
```
{THOUGHT_PAT.upper()}  Предполагая, что полученные документы содержат актуальную \
информацию о привлечении клиентов, включая список клиентов, на запрос можно ответить. Важно отметить, \
что если информация существует только в базе данных SQL, система не сможет выполнить SQL и \
не найдет ответа.
{ANSWERABLE_PAT.upper()} True
```

{QUESTION_PAT.upper()} {{user_query}}
""".strip()


# Use the following for easy viewing of prompts
if __name__ == "__main__":
    print(ANSWERABLE_PROMPT)
