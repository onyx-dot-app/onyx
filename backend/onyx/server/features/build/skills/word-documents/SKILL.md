---
name: word-documents
description: Read and create Word documents (.docx) using python-docx
---

# Working with Word Documents

User-uploaded Word documents are in `files/user_library/`. Use python-docx to read them.

## Reading Documents

```python
from docx import Document

doc = Document('files/user_library/report.docx')

# Read all paragraphs
for para in doc.paragraphs:
    print(para.text)

# Read with style information
for para in doc.paragraphs:
    print(f"Style: {para.style.name}")
    print(f"Text: {para.text}")
```

## Reading Tables

```python
from docx import Document

doc = Document('files/user_library/report.docx')

for table in doc.tables:
    for row in table.rows:
        row_data = [cell.text for cell in row.cells]
        print(row_data)
```

## Creating New Documents

Write to `outputs/`:

```python
from docx import Document
from docx.shared import Inches, Pt

doc = Document()

# Add heading
doc.add_heading('Document Title', level=0)

# Add paragraphs
doc.add_paragraph('This is a paragraph.')
doc.add_paragraph('Another paragraph with some text.')

# Add bullet points
doc.add_paragraph('First item', style='List Bullet')
doc.add_paragraph('Second item', style='List Bullet')

doc.save('outputs/new_report.docx')
```

## Adding Tables

```python
from docx import Document

doc = Document()

# Create table with 3 rows and 3 columns
table = doc.add_table(rows=3, cols=3)
table.style = 'Table Grid'

# Fill in data
for i, row in enumerate(table.rows):
    for j, cell in enumerate(row.cells):
        cell.text = f"Row {i+1}, Col {j+1}"

doc.save('outputs/table_doc.docx')
```

## Adding Images

```python
from docx import Document
from docx.shared import Inches

doc = Document()
doc.add_heading('Report with Image', level=0)
doc.add_picture('outputs/chart.png', width=Inches(5))
doc.add_paragraph('Figure 1: Chart showing data analysis')

doc.save('outputs/report_with_image.docx')
```

## Best Practices

- Files in `files/` are READ-ONLY; write to `outputs/`
- Use `doc.paragraphs` for text content
- Use `doc.tables` for tabular data
- Check document styles with `para.style.name`
