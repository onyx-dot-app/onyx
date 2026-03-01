# Directory Connector Test Data

This directory contains test files for the Directory Connector tests.

## Structure

- `code/` - Programming language files (.py, .ts, .js, etc.)
- `documents/` - Document files (.md, .txt, .json, .yaml, etc.)
- `mixed/` - Mixed content (subdirectories, various file types)

## Adding Test Files

### PDFs
To add PDF test files, place them in the `documents/` directory.

### Binary Files
For testing binary file exclusion, place test binary files (e.g., .exe, .bin, .mp3) in the `mixed/` directory.

### Large Files
For file size limit testing, you can create large files using:
```bash
dd if=/dev/zero of=test_data/mixed/large_file.txt bs=1M count=100
```

## Note
The test suite may create temporary subdirectories and files during test execution.
These are cleaned up automatically after tests complete.
