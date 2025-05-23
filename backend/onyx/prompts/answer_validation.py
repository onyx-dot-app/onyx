# The following prompts are used for verifying the LLM answer after it is already produced.
# Reflexion flow essentially. This feature can be toggled on/off
from onyx.configs.app_configs import CUSTOM_ANSWER_VALIDITY_CONDITIONS
from onyx.prompts.constants import ANSWER_PAT
from onyx.prompts.constants import QUESTION_PAT

ANSWER_VALIDITY_CONDITIONS = (
    """
1. В запросе запрашивается информация, которая зависит от конкретного человека или носит субъективный характер. Если нет \
глобально верного ответа, языковая модель не должна отвечать, поэтому любой ответ недействителен.
2. Ответ относится к связанному, но отличающемуся запросу. Чтобы быть полезной, модель может предоставлять \
соответствующую информацию о запросе, но она не будет соответствовать тому, что запрашивает пользователь, это недопустимо.
3. Ответ - это просто какая-то форма "Я не знаю" или "недостаточно информации" без существенной \
дополнительной полезной информации. Объяснение того, почему он не знает или не может ответить, неверно.
"""
    if not CUSTOM_ANSWER_VALIDITY_CONDITIONS
    else "\n".join(
        [
            f"{indice+1}. {condition}"
            for indice, condition in enumerate(CUSTOM_ANSWER_VALIDITY_CONDITIONS)
        ]
    )
)

ANSWER_FORMAT = (
    """
1. True or False
2. True or False
3. True or False
"""
    if not CUSTOM_ANSWER_VALIDITY_CONDITIONS
    else "\n".join(
        [
            f"{indice+1}. True or False"
            for indice, _ in enumerate(CUSTOM_ANSWER_VALIDITY_CONDITIONS)
        ]
    )
)

ANSWER_VALIDITY_PROMPT = f"""
Вы являетесь помощником в выявлении недопустимых пар запрос-ответ, поступающих из большой языковой модели.
Пара запрос-ответ является недопустимой, если верно любое из следующих условий:
{ANSWER_VALIDITY_CONDITIONS}

{QUESTION_PAT} {{user_query}}
{ANSWER_PAT} {{llm_answer}}

------------------------
Вы ДОЛЖНЫ ответить ТОЧНО в следующем формате:
```
{ANSWER_FORMAT}
Окончательный ответ: Valid или Invalid
```

Подсказка: Помните, что если какое-либо из условий True, то оно Invalid.
""".strip()


# Use the following for easy viewing of prompts
if __name__ == "__main__":
    print(ANSWER_VALIDITY_PROMPT)
