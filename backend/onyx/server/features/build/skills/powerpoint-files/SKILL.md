---
name: powerpoint-files
description: Read and create PowerPoint presentations (.pptx) using python-pptx
---

# Working with PowerPoint Files

User-uploaded PowerPoint files are in `files/user_library/`. Use python-pptx to read them.

## Reading Presentations

```python
from pptx import Presentation

prs = Presentation('files/user_library/deck.pptx')

# Get slide count and titles
print(f"Total slides: {len(prs.slides)}")
for i, slide in enumerate(prs.slides, 1):
    print(f"=== Slide {i} ===")

    # Extract text from shapes
    for shape in slide.shapes:
        if hasattr(shape, "text"):
            print(shape.text)

        # Handle tables
        if shape.has_table:
            for row in shape.table.rows:
                print([cell.text for cell in row.cells])

    # Speaker notes
    if slide.has_notes_slide:
        print(f"Notes: {slide.notes_slide.notes_text_frame.text}")
```

## Creating New Presentations

Write to `outputs/`:

```python
from pptx import Presentation
from pptx.util import Inches, Pt

prs = Presentation()
slide = prs.slides.add_slide(prs.slide_layouts[1])  # Title and Content
slide.shapes.title.text = "My Title"
slide.placeholders[1].text = "Bullet point content"

prs.save('outputs/new_deck.pptx')
```

## Adding Images to Slides

```python
from pptx import Presentation
from pptx.util import Inches

prs = Presentation()
slide = prs.slides.add_slide(prs.slide_layouts[6])  # Blank slide

# Add image
slide.shapes.add_picture(
    'outputs/chart.png',
    left=Inches(1),
    top=Inches(1),
    width=Inches(6)
)

prs.save('outputs/presentation_with_image.pptx')
```

## Best Practices

- Files in `files/` are READ-ONLY; write to `outputs/`
- Use `slide.shapes.title` for title shapes
- Access placeholders by index for content areas
- Check `hasattr(shape, "text")` before reading text
