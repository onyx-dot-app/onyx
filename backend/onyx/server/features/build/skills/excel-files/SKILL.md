---
name: excel-files
description: Read and process Excel spreadsheets (.xlsx, .xls) using openpyxl or pandas
---

# Working with Excel Files

User-uploaded Excel files are in `files/user_library/`. Use openpyxl or pandas to read them.

## Reading with openpyxl (Best for formulas & formatting)

```python
from openpyxl import load_workbook

# Load workbook (read_only=True for large files, data_only=True for calculated values)
wb = load_workbook('files/user_library/data.xlsx', read_only=True, data_only=True)

# List sheets
print(wb.sheetnames)

# Read specific sheet
sheet = wb['Revenue']
for row in sheet.iter_rows(min_row=1, max_row=10, values_only=True):
    print(row)
```

## Reading with pandas (Best for data analysis)

```python
import pandas as pd

# Read specific sheet into DataFrame
df = pd.read_excel('files/user_library/data.xlsx', sheet_name='Revenue')
print(df.head())

# Read all sheets
all_sheets = pd.read_excel('files/user_library/data.xlsx', sheet_name=None)
for name, df in all_sheets.items():
    print(f"Sheet: {name}, Rows: {len(df)}")
```

## Writing Modified Data

Files in `files/` are READ-ONLY. To modify:

```python
# Read, modify, write to outputs/
df = pd.read_excel('files/user_library/data.xlsx')
df['new_column'] = df['Amount'] * 1.1
df.to_excel('outputs/modified_data.xlsx', index=False)
```

## Best Practices

- Use `read_only=True` for files >10MB
- Use `data_only=True` to get calculated values (not formulas)
- For data analysis, pandas is faster; for formatting, use openpyxl
