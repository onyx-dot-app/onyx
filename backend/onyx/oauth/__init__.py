"""Shared, storage-agnostic OAuth 2.0 primitives.

A neutral leaf package (depends only on ``onyx.utils`` + ``onyx.server.security``
for the SSRF guard) so every OAuth consumer — tool OAuth, MCP servers, and Craft
external apps — can share the refresh wire layer and the single-flight refresh
orchestration without importing *up* into each other's feature packages.
"""
