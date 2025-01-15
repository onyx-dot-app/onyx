# The following prompts are used to pass each chunk to the LLM (the cheap/fast one)
# to determine if the chunk is useful towards the user query. This is used as part
# of the reranking flow

USEFUL_PAT = "Yes useful"
NONUSEFUL_PAT = "Not useful"
SECTION_FILTER_PROMPT = f"""
Determine if the following section is USEFUL for answering the user query.
It is NOT enough for the section to be related to the query, \
it must contain information that is USEFUL for answering the query.
If the section contains ANY useful information, that is good enough, \
it does not need to fully answer the every part of the user query.


Title: {{title}}
{{optional_metadata}}
Reference Section:
```
{{chunk_text}}
```

User Query:
```
{{user_query}}
```

Respond with EXACTLY AND ONLY: "{USEFUL_PAT}" or "{NONUSEFUL_PAT}"
""".strip()


# Use the following for easy viewing of prompts
if __name__ == "__main__":
    print(SECTION_FILTER_PROMPT)
