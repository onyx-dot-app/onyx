"""Basic Usage:

python scripts/chat_loadtest.py --api-key <api-key> --url <onyx-url>/api

to run from the container itself, copy this file in and run:

python chat_loadtest.py --api-key <api-key> --url localhost:8080

For more options, checkout the bottom of the file.
"""

import argparse
import asyncio
import logging
import statistics
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from logging import getLogger
from uuid import UUID

import aiohttp

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)

logger = getLogger(__name__)


@dataclass
class ChatMetrics:
    session_id: UUID
    total_time: float
    first_doc_time: float
    first_answer_time: float
    tokens_per_second: float
    total_tokens: int


class ChatLoadTester:
    def __init__(
        self,
        base_url: str,
        api_key: str | None,
        num_concurrent: int,
        messages_per_session: int,
    ):
        self.base_url = base_url
        self.headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self.num_concurrent = num_concurrent
        self.messages_per_session = messages_per_session
        self.metrics: list[ChatMetrics] = []

    async def create_chat_session(self, session: aiohttp.ClientSession) -> str:
        """Create a new chat session"""
        async with session.post(
            f"{self.base_url}/chat/create-chat-session",
            headers=self.headers,
            json={"persona_id": 0, "description": "Load Test"},
        ) as response:
            response.raise_for_status()
            data = await response.json()
            return data["chat_session_id"]

    async def process_stream(
        self, response: aiohttp.ClientResponse
    ) -> AsyncGenerator[str, None]:
        """Process the SSE stream from the chat response"""
        async for chunk in response.content:
            chunk_str = chunk.decode()
            yield chunk_str

    async def send_message(
        self,
        session: aiohttp.ClientSession,
        chat_session_id: str,
        message: str,
        parent_message_id: int | None = None,
    ) -> ChatMetrics:
        """Send a message and measure performance metrics"""
        start_time = time.time()
        first_doc_time = None
        first_answer_time = None
        token_count = 0

        async with session.post(
            f"{self.base_url}/chat/send-message",
            headers=self.headers,
            json={
                "chat_session_id": chat_session_id,
                "message": message,
                "parent_message_id": parent_message_id,
                "prompt_id": None,
                "retrieval_options": {
                    "run_search": "always",
                    "real_time": True,
                },
                "file_descriptors": [],
                "search_doc_ids": [],
            },
        ) as response:
            response.raise_for_status()

            async for chunk in self.process_stream(response):
                if "tool_name" in chunk and "run_search" in chunk:
                    if first_doc_time is None:
                        first_doc_time = time.time() - start_time

                if "answer_piece" in chunk:
                    if first_answer_time is None:
                        first_answer_time = time.time() - start_time
                    token_count += 1

            total_time = time.time() - start_time
            tokens_per_second = token_count / total_time if total_time > 0 else 0

            return ChatMetrics(
                session_id=UUID(chat_session_id),
                total_time=total_time,
                first_doc_time=first_doc_time or 0,
                first_answer_time=first_answer_time or 0,
                tokens_per_second=tokens_per_second,
                total_tokens=token_count,
            )

    async def run_chat_session(self) -> None:
        """Run a complete chat session with multiple messages"""
        async with aiohttp.ClientSession() as session:
            try:
                chat_session_id = await self.create_chat_session(session)
                messages = [
                    "Tell me about the key features of the product",
                    "How does the search functionality work?",
                    "What are the deployment options?",
                    "Can you explain the security features?",
                    "What integrations are available?",
                ]

                parent_message_id = None
                for i in range(self.messages_per_session):
                    message = messages[i % len(messages)]
                    metrics = await self.send_message(
                        session, chat_session_id, message, parent_message_id
                    )
                    self.metrics.append(metrics)
                    parent_message_id = metrics.total_tokens  # Simplified for example

            except Exception as e:
                logger.error(f"Error in chat session: {e}")

    async def run_load_test(self) -> None:
        """Run multiple concurrent chat sessions"""
        start_time = time.time()
        tasks = [self.run_chat_session() for _ in range(self.num_concurrent)]
        await asyncio.gather(*tasks)
        total_time = time.time() - start_time

        self.print_results(total_time)

    def print_results(self, total_time: float) -> None:
        """Print load test results and metrics"""
        logger.info("\n=== Load Test Results ===")
        logger.info(f"Total Time: {total_time:.2f} seconds")
        logger.info(f"Concurrent Sessions: {self.num_concurrent}")
        logger.info(f"Messages per Session: {self.messages_per_session}")
        logger.info(f"Total Messages: {len(self.metrics)}")

        if self.metrics:
            avg_response_time = statistics.mean(m.total_time for m in self.metrics)
            avg_first_doc = statistics.mean(m.first_doc_time for m in self.metrics)
            avg_first_answer = statistics.mean(
                m.first_answer_time for m in self.metrics
            )
            avg_tokens_per_sec = statistics.mean(
                m.tokens_per_second for m in self.metrics
            )

            logger.info(f"\nAverage Response Time: {avg_response_time:.2f} seconds")
            logger.info(f"Average Time to Documents: {avg_first_doc:.2f} seconds")
            logger.info(f"Average Time to First Answer: {avg_first_answer:.2f} seconds")
            logger.info(f"Average Tokens/Second: {avg_tokens_per_sec:.2f}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Chat Load Testing Tool")
    parser.add_argument(
        "--url",
        type=str,
        default="http://localhost:3000/api",
        help="Onyx URL",
    )
    parser.add_argument(
        "--api-key",
        type=str,
        help="Onyx Basic/Admin Level API key",
    )
    parser.add_argument(
        "--concurrent",
        type=int,
        default=10,
        help="Number of concurrent chat sessions",
    )
    parser.add_argument(
        "--messages",
        type=int,
        default=1,
        help="Number of messages per chat session",
    )

    args = parser.parse_args()

    load_tester = ChatLoadTester(
        base_url=args.url,
        api_key=args.api_key,
        num_concurrent=args.concurrent,
        messages_per_session=args.messages,
    )

    asyncio.run(load_tester.run_load_test())


if __name__ == "__main__":
    main()
