#!/bin/sh
# Import by numeric API key id. The key material can never be re-read,
# so the api_key attribute stays null after import.
terraform import onyx_api_key.ingest 5
