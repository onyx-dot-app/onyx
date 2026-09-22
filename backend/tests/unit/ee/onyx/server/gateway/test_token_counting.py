from onyx.server.gateway.token_counting import count_gateway_tokens


def test_image_token_estimate_does_not_tokenize_encoded_bytes() -> None:
    def count(data: str, detail: str) -> int:
        return count_gateway_tokens(
            "gpt-4o",
            [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": data, "detail": detail},
                        }
                    ],
                }
            ],
        )

    assert count("data:image/png;base64," + "abcd" * 100000, "high") == count(
        "https://example.com/image.png", "high"
    )
    assert count("image", "high") - count("image", "low") == 680
