"""
Test script for Question Qualification Service

This script tests the question qualification functionality with caching.
"""

import asyncio
import os
import sys
import unittest

# Add the project root to the path
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from onyx.server.query_and_chat.question_qualification import (
    QuestionQualificationService,
)


def main():
    print("🔍 Question Qualification Service Test")
    print("=" * 50)

    # Test basic service creation
    try:
        service = QuestionQualificationService()
        print("✅ Service created successfully")

        # Test stats
        stats = service.get_stats()
        print(f"📊 Service stats: {stats}")

        # Test simple qualification without initialization
        # This should return not blocked since initialization will fail without full app context
        async def test_qualification():
            result = await service.qualify_question("What is the capital of France?")
            print(
                f"🔍 Test qualification result: blocked={result.is_blocked}, reason={result.reason}"
            )
            return result

        result = asyncio.run(test_qualification())

        if not result.is_blocked:
            print("✅ Service correctly handles uninitialized state")
        else:
            print("❌ Service should not block when uninitialized")

    except Exception as e:
        print(f"❌ Error testing service: {e}")

    print("\n💡 To test full functionality:")
    print("   1. Start the Onyx backend server")
    print("   2. Ensure embedding model is running")
    print("   3. Try the question qualification in the chat interface")


class QuestionQualificationTest(unittest.TestCase):
    def test_singleton_pattern(self):
        """Test if the service is a singleton."""
        service1 = QuestionQualificationService()
        service2 = QuestionQualificationService()
        self.assertIs(service1, service2)

    def test_service_creation(self):
        """Test basic service creation."""
        service = QuestionQualificationService()
        self.assertIsNotNone(service)

        # Config may have enabled=True, but embedding model should be None without full app context
        self.assertIsNone(service.embedding_model)


if __name__ == "__main__":
    main()

    print("\n" + "=" * 50)
    print("Running unit tests...")
    unittest.main(verbosity=2)
