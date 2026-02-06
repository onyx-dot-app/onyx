#!/usr/bin/env python3
"""
Image generation script using Nano Banana (Google Gemini Image API).

Supports text-to-image and image-to-image generation with configurable options.
"""

import argparse
import base64
import os
import sys
from io import BytesIO
from pathlib import Path

from PIL import Image


def load_image_as_base64(image_path: str) -> tuple[str, str]:
    """Load an image file and return base64 data and mime type."""
    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"Image not found: {image_path}")

    # Determine mime type from extension
    ext = path.suffix.lower()
    mime_types = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }
    mime_type = mime_types.get(ext, "image/png")

    with open(image_path, "rb") as f:
        data = base64.b64encode(f.read()).decode("utf-8")

    return data, mime_type


def generate_image(
    prompt: str,
    output_path: str,
    model: str = "gemini-3-pro-image-preview",
    input_image: str | None = None,
    aspect_ratio: str | None = None,  # noqa: ARG001
    num_images: int = 1,
) -> list[str]:
    """
    Generate image(s) using Google Gemini / Nano Banana API.

    Args:
        prompt: Text description for image generation.
        output_path: Path to save the generated image(s).
        model: Model ID to use for generation.
        input_image: Optional path to reference image for image-to-image mode.
        aspect_ratio: Aspect ratio (e.g., "1:1", "16:9", "9:16", "4:3", "3:4").
        num_images: Number of images to generate.

    Returns:
        List of paths to saved images.
    """
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GENAI_API_KEY")
    if not api_key:
        raise ValueError(
            "API key not found. Set GEMINI_API_KEY or GENAI_API_KEY environment variable."
        )

    # lazy importing since very heavy libs
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)

    # Build content parts
    parts: list[types.Part] = []

    # Add reference image if provided (image-to-image mode)
    if input_image:
        img_data, mime_type = load_image_as_base64(input_image)
        parts.append(
            types.Part.from_bytes(
                data=base64.b64decode(img_data),
                mime_type=mime_type,
            )
        )

    # Add text prompt
    parts.append(types.Part.from_text(text=prompt))

    # Build generation config
    generate_config = types.GenerateContentConfig(
        response_modalities=["TEXT", "IMAGE"],
    )

    saved_paths: list[str] = []
    output_dir = Path(output_path).parent
    output_dir.mkdir(parents=True, exist_ok=True)

    base_name = Path(output_path).stem
    extension = Path(output_path).suffix or ".png"

    for i in range(num_images):
        response = client.models.generate_content(
            model=model,
            contents=types.Content(parts=parts),
            config=generate_config,
        )

        # Validate response
        if not response.candidates:
            raise ValueError("No candidates returned from the API")

        candidate = response.candidates[0]
        if not candidate.content or not candidate.content.parts:
            raise ValueError("No content parts returned from the API")

        # Process response parts
        image_count = 0
        for part in candidate.content.parts:
            if part.inline_data is not None and part.inline_data.data is not None:
                # Extract and save the image
                image_data = part.inline_data.data
                image = Image.open(BytesIO(image_data))

                # Generate output filename
                if num_images == 1 and image_count == 0:
                    save_path = output_path
                else:
                    save_path = str(
                        output_dir / f"{base_name}_{i + 1}_{image_count + 1}{extension}"
                    )

                image.save(save_path)
                saved_paths.append(save_path)
                print(f"Saved: {save_path}")
                image_count += 1
            elif part.text:
                # Print any text response from the model
                print(f"Model response: {part.text}")

    return saved_paths


def main() -> None:
    """Main entry point for CLI usage."""
    parser = argparse.ArgumentParser(
        description="Generate images using Nano Banana (Google Gemini Image API).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic text-to-image generation
  python generate.py --prompt "A futuristic city at sunset" --output city.png

  # Generate with specific aspect ratio
  python generate.py --prompt "Mountain landscape" --output landscape.png --aspect-ratio 16:9

  # Image-to-image mode (use reference image)
  python generate.py --prompt "Make it more colorful" --input-image ref.png --output colorful.png

  # Generate multiple images
  python generate.py --prompt "Abstract art" --output art.png --num-images 3
""",
    )

    parser.add_argument(
        "--prompt",
        "-p",
        type=str,
        required=True,
        help="Text prompt describing the desired image.",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        default="output.png",
        help="Output path for the generated image (default: output.png).",
    )
    parser.add_argument(
        "--model",
        "-m",
        type=str,
        default="gemini-3-pro-image-preview",
        help="Model to use (default: gemini-3-pro-image-preview).",
    )
    parser.add_argument(
        "--input-image",
        "-i",
        type=str,
        help="Path to reference image for image-to-image generation.",
    )
    parser.add_argument(
        "--aspect-ratio",
        "-a",
        type=str,
        choices=["1:1", "16:9", "9:16", "4:3", "3:4"],
        help="Aspect ratio for the generated image.",
    )
    parser.add_argument(
        "--num-images",
        "-n",
        type=int,
        default=1,
        help="Number of images to generate (default: 1).",
    )

    args = parser.parse_args()

    try:
        saved_paths = generate_image(
            prompt=args.prompt,
            output_path=args.output,
            model=args.model,
            input_image=args.input_image,
            aspect_ratio=args.aspect_ratio,
            num_images=args.num_images,
        )

        print(f"\nSuccessfully generated {len(saved_paths)} image(s):")
        for path in saved_paths:
            print(f"  - {path}")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
