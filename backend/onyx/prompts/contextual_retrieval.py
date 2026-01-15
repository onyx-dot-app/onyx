# NOTE: the prompt separation is partially done for efficiency; previously I tried
# to do it all in one prompt with sequential format() calls but this will cause a backend
# error when the document contains any {} as python will expect the {} to be filled by
# format() arguments

# ruff: noqa: E501, W605 start
CONTEXTUAL_RAG_PROMPT1 = """<document>
{document}
</document>
Here is the chunk we want to situate within the whole document"""

CONTEXTUAL_RAG_PROMPT2 = """<chunk>
{chunk}
</chunk>
Please give a short succinct context to situate this chunk within the overall document for the purposes of improving search retrieval of the chunk. Answer only with the succinct context and nothing else.
""".rstrip()

CONTEXTUAL_RAG_TOKEN_ESTIMATE = 64  # 19 + 45

DOCUMENT_SUMMARY_PROMPT = """<document>
{document}
</document>
Please give a short succinct summary of the entire document. Answer only with the succinct summary and nothing else.
""".rstrip()

DOCUMENT_SUMMARY_TOKEN_ESTIMATE = 50
# ruff: noqa: E501, W605 end
