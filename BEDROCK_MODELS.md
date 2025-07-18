# Amazon Bedrock Models

This document describes how to use the Bedrock environment variables to set defaults and filter models in Onyx.

## Overview
- The Bedrock default and default fast models environment variables allow you to set them to ones for which you have been granted access
- The Bedrock model filtering feature allows you to control which AWS Bedrock models are available to select in your Onyx instance by using environment variables with regex patterns.

## Environment Variables

Set these values in the `.env` file
- `BEDROCK_DEFAULT_MODEL`: Name of model to set as default.
- `BEDROCK_DEFAULT_FAST_MODEL`: Name of model to set as default. This will be set to BEDROCK_DEFAULT_MODEL if not provided
- `BEDROCK_MODEL_INCLUDE_PATTERN`: Regex pattern for models to include
- `BEDROCK_MODEL_EXCLUDE_PATTERN`: Regex pattern for models to exclude

## Filter Function Parameters

The `filter_models_by_patterns` function also supports:
- `remove_duplicates`: Whether to remove duplicate model names (default: True)

## How It Works

1. **Include Pattern**: If set, only models matching this regex pattern will be included
2. **Exclude Pattern**: If set, models matching this regex pattern will be excluded
3. **Combined**: If both patterns are set, a model must match the include pattern AND NOT match the exclude pattern

## Usage Examples

### Include Only Amazon and Anthropic Claude Models
```
BEDROCK_MODEL_INCLUDE_PATTERN="(amazon|\.anthropic\.)"
```

### Exclude Models in the APAC and EU regions
```
BEDROCK_MODEL_EXCLUDE_PATTERN=(^apac|^eu)
```

### Include Only Latest Versions
```
BEDROCK_MODEL_INCLUDE_PATTERN=-(20241022|20250219)$
```

### Combined Example
```
# Set the default model
BEDROCK_DEFAULT_MODEL="us.anthropic.claude-3-7-sonnet-20250219-v1:0"
BEDROCK_DEFAULT_FAST_MODEL="us.anthropic.claude-3-5-haiku-20241022-v1:0"
# Only show Anthropic models excluding ones in the APAC and EU regions
BEDROCK_MODEL_INCLUDE_PATTERN="(\.anthropic\.)"
BEDROCK_MODEL_EXCLUDE_PATTERN="(^apac\.|^eu\.)"
```

## Common Patterns

| Pattern | Description | Example |
|---------|-------------|---------|
| `^anthropic\.` | Models starting with "anthropic." | `anthropic.claude-3-5-sonnet` |
| `\.claude` | Models containing ".claude" | `anthropic.claude-3-5-sonnet` |
| `-20241022$` | Models ending with "-20241022" | `anthropic.claude-3-5-sonnet-20241022` |
| `(sonnet\|opus)` | Models containing "sonnet" or "opus" | `anthropic.claude-3-5-sonnet` |
| `v[12]` | Models containing "v1" or "v2" | `anthropic.claude-3-5-sonnet-v2:0` |

## Important Notes

- Patterns are case-sensitive
- Use `\.` for literal dots (not any character)
- Invalid regex patterns will be logged as warnings and ignored
- Filtering is applied at module import time
- The filtering happens after the initial model list is generated from litellm
- Duplicate model names are automatically removed (preserves order)

## Testing Patterns

You can test your regex patterns using https://regex101.com/ with Python Flavor or in Python code as shown below:

```python
import re

pattern = r"anthropic\.claude"
test_string = "anthropic.claude-3-5-sonnet-20241022-v2:0"

if re.search(pattern, test_string):
    print("Match!")
else:
    print("No match")
```

## See Also

- `backend/onyx/llm/llm_provider_options.py` - Implementation details