#!/bin/sh
# Import by numeric provider id. api_key/custom_config are masked by the
# API and stay null until set in configuration.
terraform import onyx_llm_provider.openai 3
