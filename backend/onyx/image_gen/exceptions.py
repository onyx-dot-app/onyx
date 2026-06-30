class ImageProviderError(Exception):
    pass


class ImageProviderCredentialsError(ImageProviderError):
    pass


class ImageGenerationNotConfiguredError(ImageProviderError):
    pass
