"""Egress interception proxy for Craft sandboxes.

mitmproxy-based chokepoint in front of every sandbox. Identifies which
`BuildSession` originated each outbound HTTPS call and attaches that
context to the flow. Currently pass-through (logs but does not gate).
"""
