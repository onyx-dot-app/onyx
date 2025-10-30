"""MCP Server module for Onyx.

This module implements a Model Context Protocol (MCP) server that exposes
Onyx's search capabilities, projects, and connectors to MCP clients.

Architecture:
- Separate process running on port 8081 (alongside API server on 8080)
- HTTP POST transport with API key authentication
- Hybrid access pattern: API wrapper for business logic, direct access for performance
"""
