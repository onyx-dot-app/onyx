"""Run live query and passage embeddings with the deployment's Google credentials."""

import argparse
import math
import os

import google.auth
from google.auth.compute_engine.credentials import Credentials as MetadataCredentials

from onyx.natural_language_processing.search_nlp_models import EmbeddingModel
from onyx.natural_language_processing.vertex_auth import VertexEmbeddingConfig
from shared_configs.enums import EmbeddingProvider, EmbedTextType


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--location", default="global")
    parser.add_argument("--model-name", default="gemini-embedding-2")
    parser.add_argument("--require-metadata", action="store_true")
    args = parser.parse_args()

    credentials, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    if args.require_metadata and (
        os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        or not isinstance(credentials, MetadataCredentials)
    ):
        raise RuntimeError(
            "This test requires metadata-server credentials and no credential-file override."
        )

    model = EmbeddingModel(
        server_host="localhost",
        server_port=9000,
        model_name=args.model_name,
        normalize=False,
        query_prefix=None,
        passage_prefix=None,
        api_key=None,
        api_url=None,
        provider_type=EmbeddingProvider.GOOGLE,
        reduced_dimension=768,
        vertex_config=VertexEmbeddingConfig(
            auth_method="workload_identity",
            project_id=args.project_id,
            location=args.location,
        ),
    )
    passages = model.encode(
        [
            "The launch project is called Emerald Heron.",
            "Chocolate cookies bake in the oven.",
        ],
        EmbedTextType.PASSAGE,
    )
    queries = model.encode(
        ["What is the name of the launch project?"], EmbedTextType.QUERY
    )
    if len(passages) != 2 or len(queries) != 1:
        raise RuntimeError("The provider returned an incorrect number of embeddings.")
    vectors = passages + queries
    if any(
        len(vector) != 768 or not all(math.isfinite(value) for value in vector)
        for vector in vectors
    ):
        raise RuntimeError(
            "The provider returned invalid embedding dimensions or values."
        )
    query = queries[0]
    query_norm = math.sqrt(sum(value * value for value in query))
    scores = [
        sum(a * b for a, b in zip(query, passage, strict=True))
        / (query_norm * math.sqrt(sum(value * value for value in passage)))
        for passage in passages
    ]
    if scores[0] <= scores[1]:
        raise RuntimeError("The query did not rank the relevant passage first.")
    print(
        f"PASS: {type(credentials).__module__}, {len(vectors)} vectors, 768 dimensions, scores={scores}"
    )


if __name__ == "__main__":
    main()
