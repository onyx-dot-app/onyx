"""Tool to generate all supported schema variations for Onyx Cloud's Vespa database."""

import argparse

from onyx.db.enums import EmbeddingPrecision
from onyx.document_index.vespa.index import _replace_template_values_in_schema
from onyx.document_index.vespa.index import _replace_tenant_template_value_in_schema
from onyx.document_index.vespa_constants import TENANT_ID_REPLACEMENT
from onyx.utils.logger import setup_logger
from shared_configs.configs import SUPPORTED_EMBEDDING_MODELS

logger = setup_logger()


def write_schema(index_name: str, dim: int, template: str) -> None:
    index_filename = index_name + ".sd"
    index_rendered_str = _replace_tenant_template_value_in_schema(
        template, TENANT_ID_REPLACEMENT
    )
    index_rendered_str = _replace_template_values_in_schema(
        index_rendered_str, index_name, dim, EmbeddingPrecision.FLOAT
    )

    with open(index_filename, "w", encoding="utf-8") as f:
        f.write(index_rendered_str)

    logger.info(f"Wrote {index_filename}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate multi tenant Vespa schemas")
    parser.add_argument("--template", help="The schema template to use", required=True)
    args = parser.parse_args()

    with open(args.template, "r", encoding="utf-8") as f:
        template_str = f.read()

    num_indexes = 0
    for model in SUPPORTED_EMBEDDING_MODELS:
        write_schema(model.index_name, model.dim, template_str)
        write_schema(model.index_name + "__danswer_alt_index", model.dim, template_str)
        num_indexes += 2

    logger.info(f"Wrote {num_indexes} indexes.")


if __name__ == "__main__":
    main()
