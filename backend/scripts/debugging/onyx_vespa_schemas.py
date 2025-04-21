"""Tool to generate all supported schema variations for Onyx Cloud's Vespa database."""

import argparse

import jinja2

from onyx.db.enums import EmbeddingPrecision
from onyx.utils.logger import setup_logger
from shared_configs.configs import SUPPORTED_EMBEDDING_MODELS

logger = setup_logger()


def write_schema(index_name: str, dim: int, template: jinja2.Template) -> None:
    index_filename = index_name + ".sd"

    schema = template.render(
        multi_tenant=True,
        schema_name=index_name,
        dim=dim,
        embedding_precision=EmbeddingPrecision.FLOAT.value,
    )

    with open(index_filename, "w", encoding="utf-8") as f:
        f.write(schema)

    logger.info(f"Wrote {index_filename}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate multi tenant Vespa schemas")
    parser.add_argument("--template", help="The Jinja template to use", required=True)
    args = parser.parse_args()

    jinja_env = jinja2.Environment()

    with open(args.template, "r", encoding="utf-8") as f:
        template_str = f.read()

    template = jinja_env.from_string(template_str)

    num_indexes = 0
    for model in SUPPORTED_EMBEDDING_MODELS:
        write_schema(model.index_name, model.dim, template)
        write_schema(model.index_name + "__danswer_alt_index", model.dim, template)
        num_indexes += 2

    logger.info(f"Wrote {num_indexes} indexes.")


if __name__ == "__main__":
    main()
