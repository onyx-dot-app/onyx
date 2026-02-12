---
name: image-generation
description: Generate images using nano banana.
---

# Image Generation Skill

Generate images using Nano Banana (Google Gemini Image API). Supports text-to-image and image-to-image generation with configurable options.

## Setup

### Dependencies

```bash
pip install google-genai Pillow
```

### Environment Variable

Set your API key:

```bash
export GEMINI_API_KEY="your_api_key_here"
```

## Usage

### Basic Text-to-Image

```bash
python scripts/generate.py --prompt "A futuristic city at sunset with neon lights" --output city.png
```

### With Aspect Ratio

```bash
python scripts/generate.py \
  --prompt "Mountain landscape with a lake" \
  --output landscape.png \
  --aspect-ratio 16:9
```

### Image-to-Image Mode

Use a reference image to guide generation:

```bash
python scripts/generate.py \
  --prompt "Make it look like a watercolor painting" \
  --input-image original.png \
  --output watercolor.png
```

### Generate Multiple Images

```bash
python scripts/generate.py \
  --prompt "Abstract colorful art" \
  --output art.png \
  --num-images 3
```

## Arguments

| Argument | Short | Required | Default | Description |
|----------|-------|----------|---------|-------------|
| `--prompt` | `-p` | Yes | — | Text prompt describing the desired image |
| `--output` | `-o` | No | `output.png` | Output path for the generated image |
| `--model` | `-m` | No | `gemini-2.0-flash-preview-image-generation` | Model to use for generation |
| `--input-image` | `-i` | No | — | Reference image for image-to-image mode |
| `--aspect-ratio` | `-a` | No | — | Aspect ratio: `1:1`, `16:9`, `9:16`, `4:3`, `3:4` |
| `--num-images` | `-n` | No | `1` | Number of images to generate |

## Available Models

- `gemini-2.0-flash-preview-image-generation` - Fast, optimized for speed and lower latency
- `imagen-3.0-generate-002` - High quality image generation

## Programmatic Usage

Import the function directly in Python:

```python
from scripts.generate import generate_image

paths = generate_image(
    prompt="A serene mountain lake under moonlight",
    output_path="./outputs/lake.png",
    aspect_ratio="16:9",
    num_images=2,
)
```

## Tips

- **Detailed prompts work better**: Instead of "a cat", try "a fluffy orange tabby cat sitting on a windowsill, soft morning light, photorealistic"
- **Specify style**: Include style keywords like "digital art", "oil painting", "photorealistic", "anime style"
- **Use aspect ratios**: Match the aspect ratio to your intended use (16:9 for landscapes, 9:16 for portraits/mobile)
- **Image-to-image**: Great for style transfer, variations, or guided modifications of existing images
