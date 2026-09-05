#!/bin/sh
# Import by numeric connector-credential pair id.
#
# Onyx does not report groups, auto_sync_options or processing_mode, so they
# are empty after an import. Setting them afterwards replaces the pair.
terraform import onyx_cc_pair.confluence_wiki 12
