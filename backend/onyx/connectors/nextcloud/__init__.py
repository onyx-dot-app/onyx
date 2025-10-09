"""
Nextcloud connector for Onyx - WebDAV-based file indexing.

This module provides a connector for indexing files from Nextcloud instances
using the WebDAV protocol.
"""

from .connector import NextcloudConnector

__all__ = ["NextcloudConnector"]