# Model catalog

`model_catalog.json.gz` is an offline snapshot of the [models.dev API](https://models.dev/api.json).
Requests use this file without a network lookup.
`model_catalog_overrides.json` retains supported aliases and models absent from the source.
`model_metadata_enrichments.json` supplies Onyx display metadata.

To update the snapshot, download the source and run:

```sh
curl --fail --output /tmp/models.dev.json https://models.dev/api.json
uv run python backend/scripts/update_model_catalog.py /tmp/models.dev.json
```

Review changes to context limits, vision support, reasoning support, and prices before release.
The generator converts prices per million tokens into prices per token.
Provider aliases match the names stored in Onyx configuration.
Catalog entries do not define which providers the application can connect to.
`provider_registry.py` defines supported native providers and compatible endpoints.

Cost accounting first applies administrator overrides.
It then uses `genai-prices` for provider pricing and cache tiers.
The bundled catalog supplies fallback prices for known provider and model pairs.
An unknown provider does not inherit another provider's price for the same model name.

The snapshot uses deterministic gzip compression to meet the repository file-size limit.
Decompress it with `gzip -dc backend/onyx/llm/model_catalog.json.gz` to review the JSON.
