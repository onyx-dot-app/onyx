"""
Mixin for connectors that need vision capabilities.
"""
from onyx.configs.llm_configs import get_image_extraction_and_analysis_enabled
from onyx.llm.factory import get_default_llm_with_vision
from onyx.llm.interfaces import LLM
from onyx.utils.logger import setup_logger

logger = setup_logger()


class VisionEnabledConnector:
    """
    Mixin for connectors that need vision capabilities.

    This mixin provides a standard way to initialize a vision-capable LLM
    for image analysis during indexing.

    Usage:
        class MyConnector(LoadConnector, VisionEnabledConnector):
            def __init__(self, ...):
                super().__init__(...)
                self.initialize_vision_llm()
    """

    def initialize_vision_llm(self) -> None:
        """
        Initialize a vision-capable LLM if enabled by configuration.

        Sets self.image_analysis_llm to the LLM instance or None if disabled.
        """
        self.image_analysis_llm: LLM | None = None
        if get_image_extraction_and_analysis_enabled():
            try:
                self.image_analysis_llm = get_default_llm_with_vision()
                if self.image_analysis_llm is None:
                    logger.warning(
                        "No LLM with vision found; image summarization will be disabled"
                    )
            except Exception as e:
                logger.warning(
                    f"Failed to initialize vision LLM due to an error: {str(e)}. "
                    "Image summarization will be disabled."
                )
                self.image_analysis_llm = None
