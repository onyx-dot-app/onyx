import pathlib

from onyx.file_processing.html_utils import parse_html_page_basic


def test_parse_table() -> None:
    dir_path = pathlib.Path(__file__).parent.resolve()
    with open(f"{dir_path}/test_table.html", "r") as file:
        content = file.read()

    parsed = parse_html_page_basic(content)
    expected = "\n\thello\tthere\tgeneral\n\tkenobi\ta\tb\n\tc\td\te"
    assert expected in parsed
