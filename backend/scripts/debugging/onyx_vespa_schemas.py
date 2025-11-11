"""Tool to generate all supported schema variations for Onyx Cloud's Vespa database.

Usage:

```
PYTHONPATH=. python scripts/debugging/onyx_vespa_schemas.py
```

Then, paste them into the existing vespa schema downloaded from the Vespa console,
and then re-zip.
"""

import argparse
import os
from pathlib import Path

import jinja2

from onyx.configs.embedding_configs import SUPPORTED_EMBEDDING_MODELS
from onyx.db.enums import EmbeddingPrecision
from onyx.utils.logger import setup_logger

logger = setup_logger()


def write_schema(
    index_name: str,
    dim: int,
    embedding_precision: EmbeddingPrecision,
    template: jinja2.Template,
    output_path: Path,
) -> None:
    # Create schemas directory if it doesn't exist
    schemas_dir = output_path / "schemas"
    schemas_dir.mkdir(parents=True, exist_ok=True)

    index_filename = schemas_dir / (index_name + ".sd")

    schema = template.render(
        multi_tenant=True,
        schema_name=index_name,
        dim=dim,
        embedding_precision=embedding_precision.value,
    )

    with open(index_filename, "w", encoding="utf-8") as f:
        f.write(schema)

    logger.info(f"Wrote {index_filename}")


def generate_document_entries() -> str:
    """Generate document entries for all supported embedding models."""
    document_entries = []

    for model in SUPPORTED_EMBEDDING_MODELS:
        # Add regular index
        document_entries.append(
            f'            <document type="{model.index_name}" mode="index" />'
        )
        # Add alt index
        document_entries.append(
            f'            <document type="{model.index_name}__danswer_alt_index" mode="index" />'
        )

    return "\n".join(document_entries)


def write_cloud_services(cloud_services_template_path: str, output_path: Path) -> None:
    """Generate and write the cloud-services.xml file."""
    # Create output directory if it doesn't exist
    output_path.mkdir(parents=True, exist_ok=True)

    jinja_env = jinja2.Environment()

    with open(cloud_services_template_path, "r", encoding="utf-8") as f:
        template_str = f.read()

    template = jinja_env.from_string(template_str)
    document_entries = generate_document_entries()

    services_xml = template.render(document_elements=document_entries)

    services_file = output_path / "services.xml"
    with open(services_file, "w", encoding="utf-8") as f:
        f.write(services_xml)

    logger.info(f"Wrote {services_file}")


def write_deployment_xml(
    deployment_template_path: str, output_path: Path, aws_account_id: str
) -> None:
    """Generate and write the deployment.xml file."""
    # Create output directory if it doesn't exist
    output_path.mkdir(parents=True, exist_ok=True)

    jinja_env = jinja2.Environment()

    with open(deployment_template_path, "r", encoding="utf-8") as f:
        template_str = f.read()

    template = jinja_env.from_string(template_str)
    deployment_xml = template.render(aws_account_id=aws_account_id)

    deployment_file = output_path / "deployment.xml"
    with open(deployment_file, "w", encoding="utf-8") as f:
        f.write(deployment_xml)

    logger.info(f"Wrote {deployment_file}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate multi tenant Vespa schemas and services configuration"
    )
    parser.add_argument(
        "--template",
        help="The Jinja template to use for schemas",
        default="onyx/document_index/vespa/app_config/schemas/danswer_chunk.sd.jinja",
    )
    parser.add_argument(
        "--cloud-services-template",
        help="The cloud-services.xml.jinja template path",
        default="ee/onyx/document_index/vespa/app_config/cloud-services.xml.jinja",
    )
    parser.add_argument(
        "--deployment-template",
        help="The deployment.xml.jinja template path",
        default="ee/onyx/document_index/vespa/app_config/cloud-deployment.xml.jinja",
    )
    parser.add_argument(
        "--aws-account-id",
        help="AWS Account ID for PrivateLink configuration",
        default="855178474906",
    )
    parser.add_argument(
        "--output-path",
        help="Output directory path (defaults to current directory)",
        default=".",
    )
    args = parser.parse_args()

    # Convert output path to Path object
    output_path = Path(args.output_path)

    jinja_env = jinja2.Environment()

    # Generate schema files
    with open(args.template, "r", encoding="utf-8") as f:
        template_str = f.read()

    template = jinja_env.from_string(template_str)

    num_indexes = 0
    for model in SUPPORTED_EMBEDDING_MODELS:
        write_schema(
            model.index_name,
            model.dim,
            model.embedding_precision,
            template,
            output_path,
        )
        write_schema(
            model.index_name + "__danswer_alt_index",
            model.dim,
            model.embedding_precision,
            template,
            output_path,
        )
        num_indexes += 2

    logger.info(f"Wrote {num_indexes} indexes.")

    # Generate cloud services configuration if template is provided
    if args.cloud_services_template:
        if os.path.exists(args.cloud_services_template):
            write_cloud_services(args.cloud_services_template, output_path)
        else:
            logger.error(
                f"Cloud services template not found: {args.cloud_services_template}"
            )

    # Generate deployment.xml configuration if template is provided
    if args.deployment_template:
        if os.path.exists(args.deployment_template):
            write_deployment_xml(
                args.deployment_template, output_path, args.aws_account_id
            )
        else:
            logger.error(f"Deployment template not found: {args.deployment_template}")


if __name__ == "__main__":
    main()
