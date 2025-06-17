# The following prompts are used to pass each chunk to the LLM (the cheap/fast one)
# to determine if the chunk is useful towards the user query. This is used as part
# of the reranking flow

USEFUL_PAT = "yes"
NONUSEFUL_PAT = "no"
SECTION_FILTER_PROMPT = f"""
Определи, полезен ли справочный раздел для ответа на запрос пользователя.
Недостаточно, чтобы справочный раздел был связан с запросом, \
он должен содержать информацию, полезную для ответа на запрос.
Если справочный раздел содержит какую-либо полезную информацию, этого достаточно, и \
не обязательно полностью отвечать на каждую часть запроса пользователя.


Title: {{title}}
{{optional_metadata}}
Справочный раздел:
```
{{chunk_text}}
```

Запрос пользователя:
```
{{user_query}}
```

Отвечай ТОЧНО И ТОЛЬКО: "{USEFUL_PAT}" or "{NONUSEFUL_PAT}"
""".strip()


# Use the following for easy viewing of prompts
if __name__ == "__main__":
    print(SECTION_FILTER_PROMPT)
