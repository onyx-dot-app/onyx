#!/bin/sh
# Import by numeric connector-credential pair id.
#
# Onyx reports groups, auto_sync_options and processing_mode, so the import
# reads them. A configuration that differs from them replaces the pair.
terraform import onyx_cc_pair.confluence_wiki 12
