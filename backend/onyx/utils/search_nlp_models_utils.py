def pass_aws_key(api_key: str) -> tuple[str, str, str]:
    """Parse AWS API key string into components.

    Args:
        api_key: String in format 'aws_ACCESSKEY_SECRETKEY_REGION'

    Returns:
        Tuple of (access_key, secret_key, region)

    Raises:
        ValueError: If key format is invalid
    """
    if not api_key.startswith("aws"):
        raise ValueError("API key must start with 'aws' prefix")
    parts = api_key.split("_")
    if len(parts) != 4:
        raise ValueError(
            f"API key must be in format 'aws_ACCESSKEY_SECRETKEY_REGION', got {len(parts) - 1} parts. "
            "This is an onyx specific format for formatting the aws secrets for bedrock"
        )

    try:
        _, aws_access_key_id, aws_secret_access_key, aws_region = parts
        return aws_access_key_id, aws_secret_access_key, aws_region
    except Exception as e:
        raise ValueError(f"Failed to parse AWS key components: {str(e)}")
