"""Productboard descriptions are rich text, so their blocks have to survive."""

from onyx.connectors.productboard.connector import ProductboardConnector


def test_block_elements_do_not_run_together() -> None:
    html = (
        "<h3>Quarterly Report</h3><p>Revenue rose.</p><p>Costs fell.</p>"
        "<ul><li>Item one</li><li>Item two</li></ul>"
    )

    assert ProductboardConnector._parse_description_html(html) == (
        "Quarterly Report\nRevenue rose.\nCosts fell.\n- Item one\n- Item two"
    )


def test_an_empty_description_stays_empty() -> None:
    assert ProductboardConnector._parse_description_html("") == ""
