import os

from shared_configs.ca_bundle import prefer_homebrew_ca_bundle_on_macos

prefer_homebrew_ca_bundle_on_macos()

__version__ = os.environ.get("ONYX_VERSION", "") or "Development"
