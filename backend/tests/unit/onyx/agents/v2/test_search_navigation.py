from onyx.agents.v2.search_navigation import SearchNavigation


def fixture():
    def chunk(doc, rank):
        return {
            "document_id": doc,
            "chunk_id": rank,
            "rank": rank,
            "title": doc,
            "content": doc * 4000,
            "content_total_chars": 9000,
        }

    return {
        "retrieval": {
            "retrieval_candidates": [
                {"query": "first", "returned_chunks": [chunk("a", 1), chunk("b", 2)]},
                {"query": "second", "returned_chunks": [chunk("a", 1), chunk("c", 2)]},
            ],
            "merged_candidate_document_ids_after_cap": ["a", "b"],
            "selection_stage_document_ids": {
                "selection_input": ["a", "b"],
                "selected": ["a"],
                "returned_evidence": ["a"],
            },
        }
    }


def test_provenance_diverse_alternatives_and_repetition():
    nav = SearchNavigation()
    result = nav.observe(fixture(), {1: "a"})
    assert [q["unique_to_this_query"] for q in result["queries"]] == [1, 1]
    assert [x["document_id"] for x in result["alternatives"]] == ["b", "c"]
    assert [x["stage"] for x in result["alternatives"]] == [
        "not_selected",
        "outside_merged_cap",
    ]
    assert all(len(x["excerpt"]) <= 650 for x in result["alternatives"])
    repeated = nav.observe(fixture(), {2: "a"})
    assert repeated["new_candidate_documents"] == 0
    assert repeated["repeated_candidate_documents"] == 3


def test_inspection_paging_citations_and_request_isolation():
    nav = SearchNavigation()
    handle = nav.observe(fixture(), {1: "a"})["alternatives"][0]["handle"]
    first = nav.inspect(handle, 0, 7)
    assert first.citation_mapping == {7: "b"}
    assert first.receipt["next_offset"] == 3000
    assert first.receipt["cached_passage_truncated"]
    assert nav.inspect(handle, 3000, 8).receipt["next_offset"] is None
    assert nav.inspect(handle, 4000, 9).status == "error"
    assert SearchNavigation().inspect(handle, 0, 1).status == "error"


def test_missing_diagnostics_does_not_invent_candidates():
    result = SearchNavigation().observe({}, {})
    assert not result["diagnostics_available"]
    assert result["alternatives"] == []
