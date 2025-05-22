# Freshdesk Knowledge Base Connector

This connector allows you to index content from Freshdesk Knowledge Base folders into Onyx.

## Features

- Index articles from one or multiple Freshdesk Knowledge Base folders
- Automatically handles pagination and rate limits
- Supports incremental indexing (polling)
- Includes a utility script to list all available folders

## Setup

### 1. Prerequisites

You'll need the following credentials for the Freshdesk KB connector:

- **Freshdesk Domain**: Your Freshdesk domain (e.g., `company.freshdesk.com`)
- **API Key**: Your Freshdesk API key
- **Folder ID(s)**: The ID(s) of the folder(s) you want to index

### 2. Finding Available Folders

You have several options to list available folders in your Freshdesk Knowledge Base:

#### Option 1: Backend Script

Use the provided script in the connector directory:

```bash
python backend/onyx/connectors/freshdesk_kb/scripts/list_freshdesk_kb_folders.py --domain your-domain.freshdesk.com --api-key your-api-key --pretty
```

This will output a list of all folders with their IDs and save the full details to `folders.json`.

#### Option 2: Standalone Scripts

For a more flexible approach, you can use the standalone scripts in the project root:

**Alternative approach using the same script:**
```bash
python backend/onyx/connectors/freshdesk_kb/scripts/list_freshdesk_kb_folders.py --domain your-domain.freshdesk.com --api-key your-api-key --pretty
```

This script shows:
- Folder ID
- Folder name
- Description
- Article count
- Creation date
- URL to access the folder

It also saves a detailed JSON file with folder information that you can use for future reference.

#### Multiple Folder Configuration

After listing available folders in your Freshdesk Knowledge Base, you can specify multiple folders to index.

For example, if you have folders for different topics, you might want to index several of them together:

| Folder ID    | Example Name       |
|--------------|-------------------|
| 12345        | Product Documentation |
| 67890        | FAQ                   |
| 54321        | Setup Guide           |

You can index multiple folders by combining their IDs with commas, such as: `12345,67890,54321`

### 3. Configuration

When setting up the connector in the Onyx admin interface:

1. Use the credential with your Freshdesk domain and API key
2. In the "Folder IDs" field, enter one or more folder IDs (comma-separated for multiple folders)
3. Optionally, provide the Portal URL and Portal ID for better link generation

## Advanced Options

- **Single Folder ID**: For backward compatibility only. Use the main "Folder IDs" field instead.
- **Portal URL**: The URL of your Freshdesk portal (e.g., `https://support.company.com`)
- **Portal ID**: The ID of your Freshdesk portal, used for agent URLs. You can find your Portal ID in the URL when you click on the "Solutions" button in Freshdesk - it will appear as `https://company.freshdesk.com/a/solutions?portalId=12345`

## Troubleshooting

If you encounter issues with the connector:

1. Check that your credentials (domain, API key) are correct
2. Verify that the folder IDs exist and are accessible with your API key
3. Look for error messages in the logs
4. Try indexing a single folder at a time to isolate any issues

## Implementation Details

The connector uses the Freshdesk API v2 to fetch articles from solution folders:

- Categories contain folders, which contain articles
- The connector first lists all available folders when using the folder listing script
- When indexing, it fetches articles directly from the specified folder IDs
- Each article is converted to an Onyx Document with appropriate metadata

## Performance Considerations

- Use multiple folder IDs when you need to index content from different categories
- The connector handles API rate limits automatically
- For large knowledge bases, indexing may take some time due to API pagination

## Changelog

### v1.5
- Added support for indexing multiple folders
- Improved error handling and recovery
- Added folder listing utility script
- Enhanced document yielding to prevent lost documents

### v1.0
- Initial implementation with single folder support
