VALID_MODEL_LIST = [
    "gpt-4o-mini",
    "gpt-4o",
    "gpt-4-1106-preview",
    "gpt-4-vision-preview",
    "gpt-4",
    "gpt-4-0314",
    "gpt-4-0613",
    "gpt-4-32k",
    "gpt-4-32k-0314",
    "gpt-4-32k-0613",
    "gpt-3.5-turbo-0125",
    "gpt-3.5-turbo-1106",
    "gpt-3.5-turbo",
    "gpt-3.5-turbo-16k",
    "gpt-3.5-turbo-0301",
    "gpt-3.5-turbo-0613",
    "gpt-3.5-turbo-16k-0613",
]


if __name__ == "__main__":
    from openai import OpenAI

    model_version = None
    while model_version not in VALID_MODEL_LIST:
        model_version = input("Please provide an OpenAI model version to test: ")
        if model_version not in VALID_MODEL_LIST:
            print(f"Model must be from valid list: {', '.join(VALID_MODEL_LIST)}")
    assert model_version

    api_key = input("Please provide an OpenAI API Key to test: ")
    client = OpenAI(
        api_key=api_key,
    )

    prompt = "The boy went to the "
    print(f"Asking OpenAI to finish the sentence using {model_version}")
    print(prompt)
    try:
        messages = [
            {"role": "system", "content": "Finish the sentence"},
            {"role": "user", "content": prompt},
        ]
        response = client.chat.completions.create(
            model=model_version,
            messages=messages,  # type:ignore
            max_tokens=5,
            temperature=2,
        )
        print(response.choices[0].message.content)
        print("Success! Feel free to use this API key for Onyx.")
    except Exception:
        print(
            "Failed, provided API key is invalid for Onyx, please address the error from OpenAI."
        )
        raise
