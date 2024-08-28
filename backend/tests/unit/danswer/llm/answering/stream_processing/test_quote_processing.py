import json
from datetime import datetime

from danswer.chat.models import DanswerAnswerPiece
from danswer.chat.models import DanswerQuotes
from danswer.chat.models import LlmDoc
from danswer.configs.constants import DocumentSource
from danswer.llm.answering.stream_processing.quotes_processing import (
    process_model_tokens,
)

mock_docs = [
    LlmDoc(
        document_id=f"doc_{int(id/2)}",
        content="Document is a doc",
        blurb=f"Document #{id}",
        semantic_identifier=f"Doc {id}",
        source_type=DocumentSource.WEB,
        metadata={},
        updated_at=datetime.now(),
        link=f"https://{int(id/2)}.com" if int(id / 2) % 2 == 0 else None,
        source_links={0: "https://mintlify.com/docs/settings/broken-links"},
    )
    for id in range(10)
]


tokens_with_quotes = [
    "{",
    "\n  ",
    '"answer": "Yes',
    ", Danswer allows",
    " customized prompts. This",
    " feature",
    " is currently being",
    " developed and implemente",
    "d to",
    " improve",
    " the accuracy",
    " of",
    " Language",
    " Models (",
    "LL",
    "Ms) for",
    " different",
    " companies",
    ".",
    " The custom",
    "ized prompts feature",
    " woul",
    "d allow users to ad",
    "d person",
    "alized prom",
    "pts through",
    " an",
    " interface or",
    " metho",
    "d,",
    " which would then be used to",
    " train",
    " the LLM.",
    " This enhancement",
    " aims to make",
    " Danswer more",
    " adaptable to",
    " different",
    " business",
    " contexts",
    " by",
    " tail",
    "oring it",
    " to the specific language",
    " an",
    "d terminology",
    " used within",
    " a",
    " company.",
    " Additionally",
    ",",
    " Danswer already",
    " supports creating",
    " custom AI",
    " Assistants with",
    " different",
    " prom",
    "pts and backing",
    " knowledge",
    " sets",
    ",",
    " which",
    " is",
    " a form",
    " of prompt",
    " customization. However, it",
    "'s important to nLogging Details LiteLLM-Success Call: Noneote that some",
    " aspects",
    " of prompt",
    " customization,",
    " such as for",
    " Sl",
    "ack",
    "b",
    "ots, may",
    " still",
    " be in",
    " development or have",
    ' limitations.",',
    '\n  "quotes": [',
    '\n    "We',
    " woul",
    "d like to ad",
    "d customized prompts for",
    " different",
    " companies to improve the accuracy of",
    " Language",
    " Model",
    " (LLM)",
    '.",\n    "A',
    " new",
    " feature that",
    " allows users to add personalize",
    "d prompts.",
    " This would involve",
    " creating",
    " an interface or method for",
    " users to input",
    " their",
    " own",
    " prom",
    "pts,",
    " which would then be used to",
    ' train the LLM.",',
    '\n    "Create',
    " custom AI Assistants with",
    " different prompts and backing knowledge",
    ' sets.",',
    '\n    "This',
    " PR",
    " fixes",
    " https",
    "://github.com/dan",
    "swer-ai/dan",
    "swer/issues/1",
    "584",
    " by",
    " setting",
    " the system",
    " default",
    " prompt for",
    " sl",
    "ackbots const",
    "rained by",
    " ",
    "document sets",
    ".",
    " It",
    " probably",
    " isn",
    "'t ideal",
    " -",
    " it",
    " might",
    " be pref",
    "erable to be",
    " able to select",
    " a prompt for",
    " the",
    " slackbot from",
    " the",
    " admin",
    " panel",
    " -",
    " but it sol",
    "ves the immediate problem",
    " of",
    " the slack",
    " listener",
    " cr",
    "ashing when",
    " configure",
    "d this",
    ' way."\n  ]',
    "\n}",
    "",
]


def test_process_model_tokens_answer() -> None:
    gen = process_model_tokens(tokens=iter(tokens_with_quotes), context_docs=mock_docs)

    s_json = "".join(tokens_with_quotes)
    j = json.loads(s_json)
    expected_answer = j["answer"]
    actual = ""
    for o in gen:
        if isinstance(o, DanswerAnswerPiece):
            if o.answer_piece:
                actual += o.answer_piece

    assert expected_answer == actual


def test_simple_json_answer() -> None:
    tokens = [
        "```",
        "json",
        "\n",
        "{",
        '"answer": "This is a simple ',
        "answer.",
        '",\n"',
        'quotes": []',
        "\n}",
        "\n",
        "```",
    ]
    gen = process_model_tokens(tokens=iter(tokens), context_docs=mock_docs)

    expected_answer = "This is a simple answer."
    actual = "".join(
        o.answer_piece
        for o in gen
        if isinstance(o, DanswerAnswerPiece) and o.answer_piece
    )

    assert expected_answer == actual


def test_json_answer_with_quotes() -> None:
    tokens = [
        "```",
        "json",
        "\n",
        "{",
        '"answer": "This ',
        "is a ",
        "split ",
        "answer.",
        '",\n"',
        'quotes": []',
        "\n}",
        "\n",
        "```",
    ]
    gen = process_model_tokens(tokens=iter(tokens), context_docs=mock_docs)

    expected_answer = "This is a split answer."
    actual = "".join(
        o.answer_piece
        for o in gen
        if isinstance(o, DanswerAnswerPiece) and o.answer_piece
    )

    assert expected_answer == actual


def test_json_answer_split_tokens() -> None:
    tokens = [
        "```",
        "json",
        "\n",
        "{",
        '\n"',
        'answer": "This ',
        "is a ",
        "split ",
        "answer.",
        '",\n"',
        'quotes": []',
        "\n}",
        "\n",
        "```",
    ]
    gen = process_model_tokens(tokens=iter(tokens), context_docs=mock_docs)

    expected_answer = "This is a split answer."
    actual = "".join(
        o.answer_piece
        for o in gen
        if isinstance(o, DanswerAnswerPiece) and o.answer_piece
    )

    assert expected_answer == actual


def test_lengthy_prefixed_json_with_quotes() -> None:
    tokens = [
        "This is my response in json\n\n",
        "```",
        "json",
        "\n",
        "{",
        '"answer": "This is a simple ',
        "answer.",
        '",\n"',
        'quotes": ["Document"]',
        "\n}",
        "\n",
        "```",
    ]

    gen = process_model_tokens(tokens=iter(tokens), context_docs=mock_docs)

    actual_answer = ""
    actual_count = 0
    for o in gen:
        if isinstance(o, DanswerAnswerPiece):
            if o.answer_piece:
                actual_answer += o.answer_piece
            continue

        if isinstance(o, DanswerQuotes):
            for q in o.quotes:
                assert q.quote == "Document"
                actual_count += 1
    assert "This is a simple answer." == actual_answer
    assert 1 == actual_count


def test_prefixed_json_with_quotes() -> None:
    tokens = [
        "```",
        "json",
        "\n",
        "{",
        '"answer": "This is a simple ',
        "answer.",
        '",\n"',
        'quotes": ["Document"]',
        "\n}",
        "\n",
        "```",
    ]

    gen = process_model_tokens(tokens=iter(tokens), context_docs=mock_docs)

    actual_answer = ""
    actual_count = 0
    for o in gen:
        if isinstance(o, DanswerAnswerPiece):
            if o.answer_piece:
                actual_answer += o.answer_piece
            continue

        if isinstance(o, DanswerQuotes):
            for q in o.quotes:
                assert q.quote == "Document"
                actual_count += 1

    assert "This is a simple answer." == actual_answer
    assert 1 == actual_count
