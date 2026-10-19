"""Regression checks for catalog imports, descriptions, and paths."""

import unittest

import generate_catalog as catalog


class CatalogTests(unittest.TestCase):
    def test_public_imports_and_repository_paths(self) -> None:
        rendered = catalog.render()
        for name in ("OnyxLoader", "AuthLayouts", "InputVertical, InputHorizontal"):
            self.assertIn(f"| `{name}` |", rendered)
        for row in rendered.splitlines():
            if "README.md` |" in row:
                path = row.split("`")[-2]
                self.assertTrue((catalog._REPO / path).is_file(), path)

    def test_upload_description_skips_formik_import(self) -> None:
        rendered = catalog.render()
        for name in ("InputSingleUpload", "InputMultiUpload"):
            row = next(
                line
                for line in rendered.splitlines()
                if line.startswith(f"| `{name}` |")
            )
            self.assertNotIn("import {", row)
            self.assertNotIn("**Formik:**", row)

    def test_only_adjacent_component_doc_is_used(self) -> None:
        self.assertEqual(
            catalog._jsdoc_description(
                "/** A useful control. */\nexport default function Control() {}"
            ),
            "A useful control.",
        )
        for source in (
            "/** A prop. */\ninterface Props {}\nexport default function Control() {}",
            "/** A helper. */\nfunction helper() {}\nexport default function Control() {}",
            "/** A prop. */\nconst Control = () => null;\nexport default Control;",
        ):
            self.assertEqual(catalog._jsdoc_description(source), "")


if __name__ == "__main__":
    unittest.main()
