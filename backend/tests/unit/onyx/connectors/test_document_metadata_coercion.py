from onyx.configs.constants import DocumentSource
from onyx.connectors.models import Document
from onyx.connectors.models import DocumentBase
from onyx.connectors.models import TextSection


def _minimal_doc_kwargs(metadata: dict) -> dict:
    return {
        "id": "test-doc",
        "sections": [TextSection(text="hello", link="http://example.com")],
        "source": DocumentSource.NOT_APPLICABLE,
        "semantic_identifier": "Test Doc",
        "metadata": metadata,
    }


def test_int_values_coerced_to_str() -> None:
    doc = Document(**_minimal_doc_kwargs({"count": 42}))
    assert doc.metadata == {"count": "42"}


def test_float_values_coerced_to_str() -> None:
    doc = Document(**_minimal_doc_kwargs({"score": 3.14}))
    assert doc.metadata == {"score": "3.14"}


def test_bool_values_coerced_to_str() -> None:
    doc = Document(**_minimal_doc_kwargs({"active": True}))
    assert doc.metadata == {"active": "True"}


def test_list_of_ints_coerced_to_list_of_str() -> None:
    doc = Document(**_minimal_doc_kwargs({"ids": [1, 2, 3]}))
    assert doc.metadata == {"ids": ["1", "2", "3"]}


def test_list_of_mixed_types_coerced_to_list_of_str() -> None:
    doc = Document(**_minimal_doc_kwargs({"tags": ["a", 1, True, 2.5]}))
    assert doc.metadata == {"tags": ["a", "1", "True", "2.5"]}


def test_list_of_dicts_coerced_to_list_of_str() -> None:
    raw = {"nested": [{"key": "val"}, {"key2": "val2"}]}
    doc = Document(**_minimal_doc_kwargs(raw))
    assert doc.metadata == {"nested": ["{'key': 'val'}", "{'key2': 'val2'}"]}


def test_dict_value_coerced_to_str() -> None:
    raw = {"info": {"inner_key": "inner_val"}}
    doc = Document(**_minimal_doc_kwargs(raw))
    assert doc.metadata == {"info": "{'inner_key': 'inner_val'}"}


def test_none_value_coerced_to_str() -> None:
    doc = Document(**_minimal_doc_kwargs({"empty": None}))
    assert doc.metadata == {"empty": "None"}


def test_already_valid_str_values_unchanged() -> None:
    doc = Document(**_minimal_doc_kwargs({"key": "value"}))
    assert doc.metadata == {"key": "value"}


def test_already_valid_list_of_str_unchanged() -> None:
    doc = Document(**_minimal_doc_kwargs({"tags": ["a", "b", "c"]}))
    assert doc.metadata == {"tags": ["a", "b", "c"]}


def test_empty_metadata_unchanged() -> None:
    doc = Document(**_minimal_doc_kwargs({}))
    assert doc.metadata == {}


def test_mixed_metadata_values() -> None:
    raw = {
        "str_val": "hello",
        "int_val": 99,
        "list_val": [1, "two", 3.0],
        "dict_val": {"nested": True},
    }
    doc = Document(**_minimal_doc_kwargs(raw))
    assert doc.metadata == {
        "str_val": "hello",
        "int_val": "99",
        "list_val": ["1", "two", "3.0"],
        "dict_val": "{'nested': True}",
    }


def test_coercion_works_on_base_class() -> None:
    kwargs = _minimal_doc_kwargs({"count": 42})
    kwargs.pop("source")
    kwargs.pop("id")
    doc = DocumentBase(**kwargs)
    assert doc.metadata == {"count": "42"}
