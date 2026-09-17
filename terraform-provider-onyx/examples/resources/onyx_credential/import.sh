#!/bin/sh
# Import by numeric credential id. Onyx only returns the payload masked, so
# credential_json stays at its configured value and is never refreshed.
terraform import onyx_credential.confluence 12
