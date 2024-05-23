import pathlib
import unittest

from danswer.file_processing.html_utils import parse_html_page_basic


class TestQAPostprocessing(unittest.TestCase):
    def test_parse_table(self) -> None:
        dir_path = pathlib.Path(__file__).parent.resolve()
        with open(f"{dir_path}/test_table.html", "r") as file:
            content = file.read()

        parsed = parse_html_page_basic(content)
        expected = "\n\thello\tthere\tgeneral\n\tkenobi\ta\tb\n\tc\td\te"
        self.assertIn(expected, parsed)


if __name__ == "__main__":
    unittest.main()
