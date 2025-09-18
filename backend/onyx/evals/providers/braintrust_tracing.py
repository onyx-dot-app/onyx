from collections.abc import Sequence
from re import Pattern
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from uuid import UUID

from braintrust_langchain import set_global_handler
from braintrust_langchain.callbacks import BraintrustCallbackHandler
from langchain_core.agents import AgentAction
from langchain_core.agents import AgentFinish
from langchain_core.documents import Document
from langchain_core.messages import BaseMessage
from langchain_core.outputs.llm_result import LLMResult
from tenacity import RetryCallState


def _truncate_to_chars(obj: Any, max_chars: int = 10_000) -> Any:
    """
    Truncate any object to first max_chars characters and note that it's been truncated.

    Args:
        obj: The object to potentially truncate
        max_chars: Maximum number of characters to keep

    Returns:
        Truncated object with truncation note if it was truncated
    """
    if obj is None:
        return obj

    obj_str = str(obj)

    if len(obj_str) <= max_chars:
        return obj

    truncated_str = obj_str[:max_chars]
    return f"{truncated_str}\n... [TRUNCATED: {len(obj_str):,} characters -> {max_chars:,} characters]"


class OnyxBraintrustCallbackHandler(BraintrustCallbackHandler):
    """
    Custom Braintrust callback handler with input/output truncation functionality.

    Inherits from BraintrustCallbackHandler and implements all required LangChain
    callback methods with proper truncation of data sent to Braintrust.
    """

    def __init__(
        self,
        logger: Optional[Any] = None,
        debug: bool = False,
        exclude_metadata_props: Optional[Pattern[str]] = None,
        max_chars: int = 10_000,
    ):
        super().__init__(logger, debug, exclude_metadata_props)
        self.max_chars = max_chars

    def on_agent_action(
        self,
        action: AgentAction,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> Any:
        """Run on agent action."""
        # Truncate the tool input before passing to parent
        truncated_input = _truncate_to_chars(action.tool_input, self.max_chars)

        # Create a modified action with truncated input
        modified_action = AgentAction(
            tool=action.tool,
            tool_input=truncated_input,
            log=action.log,
        )

        return super().on_agent_action(
            modified_action, run_id=run_id, parent_run_id=parent_run_id, **kwargs
        )

    def on_agent_finish(
        self,
        finish: AgentFinish,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> Any:
        """Run on the agent end."""
        # Truncate the return values before passing to parent
        truncated_output = _truncate_to_chars(finish.return_values, self.max_chars)

        # Create a modified finish with truncated output
        modified_finish = AgentFinish(
            return_values=truncated_output,
            log=finish.log,
        )

        return super().on_agent_finish(
            modified_finish, run_id=run_id, parent_run_id=parent_run_id, **kwargs
        )

    def on_chain_end(
        self,
        outputs: Dict[str, Any],
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> Any:
        """Run when chain ends running."""
        # Truncate the outputs before passing to parent
        truncated_outputs = _truncate_to_chars(outputs, self.max_chars)

        return super().on_chain_end(
            truncated_outputs, run_id=run_id, parent_run_id=parent_run_id, **kwargs
        )

    def on_chain_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> Any:
        """Run when chain errors."""
        return super().on_chain_error(
            error, run_id=run_id, parent_run_id=parent_run_id, **kwargs
        )

    def on_chain_start(
        self,
        serialized: Dict[str, Any],
        inputs: Dict[str, Any],
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> Any:
        """Run when a chain starts running."""
        # Truncate the inputs before passing to parent
        truncated_inputs = _truncate_to_chars(inputs, self.max_chars)

        return super().on_chain_start(
            serialized,
            truncated_inputs,
            run_id=run_id,
            parent_run_id=parent_run_id,
            **kwargs,
        )

    def on_chat_model_start(
        self,
        serialized: Dict[str, Any],
        messages: List[List[BaseMessage]],
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> Any:
        """Run when a chat model starts running."""
        # Truncate the messages before passing to parent
        truncated_messages = _truncate_to_chars(messages, self.max_chars)

        return super().on_chat_model_start(
            serialized,
            truncated_messages,
            run_id=run_id,
            parent_run_id=parent_run_id,
            **kwargs,
        )

    def on_custom_event(
        self,
        name: str,
        data: Any,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> Any:
        """Override to define a handler for a custom event."""
        # Truncate the data before passing to parent
        truncated_data = _truncate_to_chars(data, self.max_chars)

        return super().on_custom_event(name, truncated_data, run_id=run_id, **kwargs)

    def on_llm_end(
        self,
        response: LLMResult,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> Any:
        """Run when LLM ends running."""
        # Truncate the response before passing to parent
        truncated_response = _truncate_to_chars(response, self.max_chars)

        return super().on_llm_end(
            truncated_response, run_id=run_id, parent_run_id=parent_run_id, **kwargs
        )

    def on_llm_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> Any:
        """Run when LLM errors."""
        return super().on_llm_error(
            error, run_id=run_id, parent_run_id=parent_run_id, **kwargs
        )

    def on_llm_new_token(
        self,
        token: str,
        *,
        chunk: Optional[Any] = None,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> Any:
        """Run on new output token."""
        # Truncate the token if it's too long
        truncated_token = _truncate_to_chars(token, self.max_chars)

        return super().on_llm_new_token(
            truncated_token,
            chunk=chunk,
            run_id=run_id,
            parent_run_id=parent_run_id,
            **kwargs,
        )

    def on_llm_start(
        self,
        serialized: Dict[str, Any],
        prompts: List[str],
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> Any:
        """Run when LLM starts running."""
        # Truncate the prompts before passing to parent
        truncated_prompts = _truncate_to_chars(prompts, self.max_chars)

        return super().on_llm_start(
            serialized,
            truncated_prompts,
            run_id=run_id,
            parent_run_id=parent_run_id,
            **kwargs,
        )

    def on_retriever_end(
        self,
        documents: Sequence[Document],
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> Any:
        """Run when Retriever ends running."""
        # Truncate the documents before passing to parent
        truncated_documents = _truncate_to_chars(documents, self.max_chars)

        return super().on_retriever_end(
            truncated_documents, run_id=run_id, parent_run_id=parent_run_id, **kwargs
        )

    def on_retriever_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> Any:
        """Run when Retriever errors."""
        return super().on_retriever_error(
            error, run_id=run_id, parent_run_id=parent_run_id, **kwargs
        )

    def on_retriever_start(
        self,
        serialized: Dict[str, Any],
        query: str,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> Any:
        """Run when the Retriever starts running."""
        # Truncate the query before passing to parent
        truncated_query = _truncate_to_chars(query, self.max_chars)

        return super().on_retriever_start(
            serialized,
            truncated_query,
            run_id=run_id,
            parent_run_id=parent_run_id,
            **kwargs,
        )

    def on_retry(
        self,
        retry_state: RetryCallState,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> Any:
        """Run on a retry event."""
        return super().on_retry(
            retry_state, run_id=run_id, parent_run_id=parent_run_id, **kwargs
        )

    def on_text(
        self,
        text: str,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> Any:
        """Run on an arbitrary text."""
        # Truncate the text before passing to parent
        truncated_text = _truncate_to_chars(text, self.max_chars)

        return super().on_text(
            truncated_text, run_id=run_id, parent_run_id=parent_run_id, **kwargs
        )

    def on_tool_end(
        self,
        output: Any,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> Any:
        """Run when the tool ends running."""
        # Truncate the output before passing to parent
        truncated_output = _truncate_to_chars(output, self.max_chars)

        return super().on_tool_end(
            truncated_output, run_id=run_id, parent_run_id=parent_run_id, **kwargs
        )

    def on_tool_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> Any:
        """Run when tool errors."""
        return super().on_tool_error(
            error, run_id=run_id, parent_run_id=parent_run_id, **kwargs
        )

    def on_tool_start(
        self,
        serialized: Dict[str, Any],
        input_str: str,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> Any:
        """Run when the tool starts running."""
        # Truncate the input string before passing to parent
        truncated_input_str = _truncate_to_chars(input_str, self.max_chars)

        return super().on_tool_start(
            serialized,
            truncated_input_str,
            run_id=run_id,
            parent_run_id=parent_run_id,
            **kwargs,
        )


def setup_braintrust() -> None:
    """Initialize Braintrust logger and set up global callback handler."""

    # braintrust.init_logger(
    #     project=BRAINTRUST_PROJECT,
    #     api_key=BRAINTRUST_API_KEY,
    # )
    handler = OnyxBraintrustCallbackHandler()
    set_global_handler(handler)
