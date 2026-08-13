#!/bin/sh
# Import by numeric connector id. access_type and groups live on the cc-pair,
# so they return to their defaults after import.
terraform import onyx_connector.docs_site 5
