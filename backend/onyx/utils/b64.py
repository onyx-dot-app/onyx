import base64


def get_image_type_from_bytes(raw_b64_bytes: bytes) -> str:
    magic_number = raw_b64_bytes[:4]

    if magic_number.startswith(b"\x89PNG"):
        mime_type = "image/png"
    elif magic_number.startswith(b"\xff\xd8"):
        mime_type = "image/jpeg"
    elif magic_number.startswith(b"GIF8"):
        mime_type = "image/gif"
    elif magic_number.startswith(b"RIFF") and raw_b64_bytes[8:12] == b"WEBP":
        mime_type = "image/webp"
    else:
        raise ValueError(
            "Unsupported image format - only PNG, JPEG, GIF, and WEBP are supported."
        )

    return mime_type


def get_image_type(raw_b64_string: str) -> str:
    binary_data = base64.b64decode(raw_b64_string)
    return get_image_type_from_bytes(binary_data)


def normalize_image_for_llm(image_data: bytes) -> tuple[bytes, str]:
    """Return image bytes and MIME type in a vision-LLM-supported format.

    Vision APIs accept only PNG/JPEG/GIF/WEBP, but document extraction can
    surface other formats — scanned PDFs typically embed their pages as
    CCITT-compressed TIFFs. Anything PIL can decode is transcoded to PNG;
    undecodable data raises ValueError like get_image_type_from_bytes.
    """
    try:
        return image_data, get_image_type_from_bytes(image_data)
    except ValueError:
        pass

    import io

    from PIL import Image

    try:
        with Image.open(io.BytesIO(image_data)) as img:
            output = io.BytesIO()
            try:
                img.save(output, format="PNG")
            except (OSError, ValueError):
                # Modes PNG can't store directly (e.g. CMYK)
                output = io.BytesIO()
                img.convert("RGB").save(output, format="PNG")
    except Exception as exc:
        raise ValueError(
            "Unsupported image format - could not identify or transcode to PNG."
        ) from exc

    return output.getvalue(), "image/png"
