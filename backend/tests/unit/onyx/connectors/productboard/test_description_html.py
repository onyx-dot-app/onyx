"""Productboard descriptions are rich text, so their blocks have to survive."""

from onyx.connectors.productboard.connector import ProductboardConnector


def test_block_elements_do_not_run_together() -> None:
    html = (
        "<h3>Quarterly Report</h3><p>Revenue rose.</p><p>Costs fell.</p>"
        "<ul><li>Item one</li><li>Item two</li></ul>"
    )

    text = ProductboardConnector._parse_description_html(html)

    assert "ReportRevenue" not in text
    assert "Quarterly Report" in text
    assert "Revenue rose." in text
    assert "Item one" in text
    assert "Item two" in text
    # One line per block, the way the description reads.
    assert len(text.splitlines()) == 5


def test_an_empty_description_stays_empty() -> None:
    assert ProductboardConnector._parse_description_html("") == ""
