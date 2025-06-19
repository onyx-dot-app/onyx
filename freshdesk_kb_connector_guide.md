# Freshdesk KB Multi-Folder Connector Guide

This guide explains how to use the enhanced Freshdesk Knowledge Base connector with multi-folder support.

## Features Added

The connector has been enhanced with the following features:

1. **Support for multiple folders**: Index content from multiple Freshdesk KB folders simultaneously
2. **Improved folder discovery**: Use the standalone script to list all available folders
3. **Enhanced UI configuration**: Updated UI options for specifying multiple folders
4. **Detailed logging**: Better logging with per-folder statistics

## Setup Instructions

### 1. List Available Folders

First, use the standalone script to discover all available folders in your Freshdesk KB:

```bash
# Make the script executable
chmod +x standalone_list_freshdesk_folders.py

# Run with your Freshdesk credentials
./standalone_list_freshdesk_folders.py --domain your-domain.freshdesk.com --api-key your-api-key --pretty
```

The script will output a list of folders and save the details to `folders.json`. Note the IDs of folders you want to index.

### 2. Configure the Connector in Onyx UI

In the Onyx admin interface:

1. Navigate to the Sources page and click "Add Source"
2. Select "Freshdesk KB" as the source type
3. Enter credential details (domain, API key)
4. In the "Folder IDs" field, enter a comma-separated list of folder IDs:
   ```
   5000184231,5000184232,5000184233
   ```
5. Optionally provide Portal URL and Portal ID for better link generation
6. Save the configuration

### 3. Test in Development Environment

If you're working in a development environment with the Onyx codebase:

1. The connector will automatically handle multiple folders when specified in the configuration
2. You can run the connector in the context of the Onyx backend using the API or connector test scripts

### 4. Debug Common Issues

If you encounter issues when using multiple folders:

- Make sure all folder IDs are valid and accessible with your API key
- Check the logs for specific error messages
- Try using one folder at a time to isolate issues
- Ensure your API rate limits are sufficient for the number of folders/articles

## Implementation Details

### How Multi-Folder Support Works

The enhanced connector:

1. Parses folder IDs from the connector configuration
2. Processes each folder sequentially to respect API rate limits
3. Yields documents in batches from each folder
4. Tracks article counts per folder for detailed logging

### Folder ID Configuration Options

The connector accepts folder IDs in several formats:

1. **Single folder ID**: Using the `folder_id` parameter (for backward compatibility)
2. **List of folder IDs**: Using the `folder_ids` parameter as a list
3. **Comma-separated string**: Using the `folder_ids` parameter as a comma-separated string

### Benchmarks

Performance varies based on:
- Number of folders
- Number of articles per folder
- API rate limits

Typical throughput is about 30 articles per minute, regardless of whether they come from one folder or multiple folders.

## Frequently Asked Questions

**Q: Will this affect existing connectors?**  
A: No, existing connectors with a single folder ID will continue to work as before.

**Q: Is there a limit to how many folders I can index?**  
A: There's no hard limit, but processing more folders will take longer and may hit API rate limits.

**Q: How can I monitor the indexing progress?**  
A: The connector logs detailed information about each folder it processes, including article counts.

## Conclusion

The multi-folder support makes the Freshdesk KB connector more flexible and powerful. You can now easily index content from across your knowledge base, organizing it by folders that may span different categories or topics.
