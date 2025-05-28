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
            "Unsupported image format - only PNG, JPEG, " "GIF, and WEBP are supported."
        )

    return mime_type


def get_image_type(raw_b64_string: str) -> str:
    binary_data = base64.b64decode(raw_b64_string)
    return get_image_type_from_bytes(binary_data)
