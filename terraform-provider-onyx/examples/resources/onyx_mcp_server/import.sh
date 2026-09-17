#!/bin/sh
# Import by numeric server id. Credentials are returned masked, so an imported
# server carries none: put api_token or admin_credentials back in the
# configuration before the next apply.
terraform import onyx_mcp_server.weather 3
