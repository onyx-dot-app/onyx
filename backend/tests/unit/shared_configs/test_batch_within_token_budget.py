from shared_configs.utils import batch_within_token_budget


def _length(text: str) -> int:
    return len(text)


class TestBatchWithinTokenBudget:
    def test_item_count_caps_when_tokens_are_cheap(self) -> None:
        batches = batch_within_token_budget(
            ["a"] * 25, max_items=10, max_tokens=1_000, estimate_tokens=_length
        )

        assert [len(batch) for batch in batches] == [10, 10, 5]

    def test_token_budget_caps_before_the_item_count(self) -> None:
        batches = batch_within_token_budget(
            ["abcd"] * 10, max_items=10, max_tokens=10, estimate_tokens=_length
        )

        assert [len(batch) for batch in batches] == [2, 2, 2, 2, 2]
        for batch in batches:
            assert sum(_length(item) for item in batch) <= 10

    def test_item_over_the_whole_budget_is_isolated(self) -> None:
        batches = batch_within_token_budget(
            ["a", "x" * 50, "b"], max_items=10, max_tokens=10, estimate_tokens=_length
        )

        assert batches == [["a"], ["x" * 50], ["b"]]

    def test_every_item_is_kept_once_and_in_order(self) -> None:
        items = [f"item-{i}" * (i % 5 + 1) for i in range(100)]

        batches = batch_within_token_budget(
            items, max_items=7, max_tokens=40, estimate_tokens=_length
        )

        assert [item for batch in batches for item in batch] == items

    def test_empty_input_produces_no_batches(self) -> None:
        assert (
            batch_within_token_budget(
                [], max_items=10, max_tokens=10, estimate_tokens=_length
            )
            == []
        )

    def test_works_on_non_string_items(self) -> None:
        """The helper is generic; callers supply the token estimate."""
        batches = batch_within_token_budget(
            [3, 3, 3, 3], max_items=10, max_tokens=6, estimate_tokens=lambda n: n
        )

        assert batches == [[3, 3], [3, 3]]
