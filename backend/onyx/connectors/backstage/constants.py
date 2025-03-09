"""
Constants for the Backstage connector.
"""

# Default API paths
DEFAULT_API_PATH = "/api/catalog"
ENTITIES_PATH = "/entities"
ENTITY_BY_NAME_PATH = "/entities/by-name"

# Default request parameters
DEFAULT_PAGE_SIZE = 100

# API response keys
METADATA_KEY = "metadata"
KIND_KEY = "kind"
NAME_KEY = "name"
NAMESPACE_KEY = "namespace"
SPEC_KEY = "spec"
RELATIONS_KEY = "relations"
DESCRIPTION_KEY = "description"

# Entity relation types of interest
RELATION_DEPENDS_ON = "dependsOn"
RELATION_PROVIDES_API = "providesApi"
RELATION_CONSUMES_API = "consumesApi"
RELATION_OWNED_BY = "ownedBy"
RELATION_PART_OF = "partOf"

# Timeout configuration in seconds
REQUEST_TIMEOUT = 30