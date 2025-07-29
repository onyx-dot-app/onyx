import http.server
import os
import shutil
import tempfile
import threading
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime
from datetime import timezone
from time import sleep
from typing import Any

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from onyx.server.documents.models import DocumentSource
from onyx.utils.logger import setup_logger
from tests.integration.common_utils.managers.api_key import APIKeyManager
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.common_utils.vespa import vespa_fixture

logger = setup_logger()


# FastAPI server for serving files
def create_fastapi_app(directory: str) -> FastAPI:
    app = FastAPI()

    # Mount the directory to serve static files
    app.mount("/", StaticFiles(directory=directory, html=True), name="static")

    return app


# as far as we know, this doesn't hang when crawled. This is good.
@contextmanager
def fastapi_server_context(
    directory: str, port: int = 8000
) -> Generator[None, None, None]:
    app = create_fastapi_app(directory)

    config = uvicorn.Config(app=app, host="0.0.0.0", port=port, log_level="info")
    server = uvicorn.Server(config)

    # Create a thread to run the FastAPI server
    server_thread = threading.Thread(target=server.run)
    server_thread.daemon = (
        True  # Ensures the thread will exit when the main program exits
    )

    try:
        # Start the server in the background
        server_thread.start()
        sleep(5)  # Give it a few seconds to start
        yield  # Yield control back to the calling function (context manager in use)
    finally:
        # Shutdown the server
        server.should_exit = True
        server_thread.join()


# Leaving this here for posterity and experimentation, but the reason we're
# not using this is python's web servers hang frequently when crawled
# this is obviously not good for a unit test
@contextmanager
def http_server_context(
    directory: str, port: int = 8000
) -> Generator[http.server.ThreadingHTTPServer, None, None]:
    # Create a handler that serves files from the specified directory
    def handler_class(
        *args: Any, **kwargs: Any
    ) -> http.server.SimpleHTTPRequestHandler:
        return http.server.SimpleHTTPRequestHandler(
            *args, directory=directory, **kwargs
        )

    # Create an HTTPServer instance
    httpd = http.server.ThreadingHTTPServer(("0.0.0.0", port), handler_class)

    # Define a thread that runs the server in the background
    server_thread = threading.Thread(target=httpd.serve_forever)
    server_thread.daemon = (
        True  # Ensures the thread will exit when the main program exits
    )

    try:
        # Start the server in the background
        server_thread.start()
        sleep(5)  # give it a few seconds to start
        yield httpd
    finally:
        # Shutdown the server and wait for the thread to finish
        httpd.shutdown()
        httpd.server_close()
        server_thread.join()


def test_web_pruning(reset: None, vespa_client: vespa_fixture) -> None:
    # Creating an admin user (first user created is automatically an admin)
    admin_user: DATestUser = UserManager.create(name="admin_user")

    # add api key to user
    APIKeyManager.create(
        user_performing_action=admin_user,
    )

    test_filename = os.path.realpath(__file__)
    test_directory = os.path.dirname(test_filename)
    with tempfile.TemporaryDirectory() as temp_dir:
        port = 8889

        website_src = os.path.join(test_directory, "website")
        website_tgt = os.path.join(temp_dir, "website")
        shutil.copytree(website_src, website_tgt)
        with fastapi_server_context(os.path.join(temp_dir, "website"), port):
            sleep(1)  # sleep a tiny bit before starting everything

            hostname = os.getenv("TEST_WEB_HOSTNAME", "localhost")
            config = {
                "base_url": f"http://{hostname}:{port}/",
                "web_connector_type": "recursive",
            }

            # store the time before we create the connector so that we know after
            # when the indexing should have started
            now = datetime.now(timezone.utc)

            # create connector
            cc_pair_1 = CCPairManager.create_from_scratch(
                source=DocumentSource.WEB,
                connector_specific_config=config,
                user_performing_action=admin_user,
            )

            CCPairManager.wait_for_indexing_completion(
                cc_pair_1, now, timeout=300, user_performing_action=admin_user
            )

            selected_cc_pair = CCPairManager.get_indexing_status_by_id(
                cc_pair_1.id, user_performing_action=admin_user
            )

            assert selected_cc_pair is not None, "cc_pair not found after indexing!"

            # used to be 15, but now
            # localhost:8889/ and localhost:8889/index.html are deduped
            assert selected_cc_pair.docs_indexed == 14

            logger.info("Removing about.html.")
            os.remove(os.path.join(website_tgt, "about.html"))
            logger.info("Removing courses.html.")
            os.remove(os.path.join(website_tgt, "courses.html"))

            now = datetime.now(timezone.utc)
            CCPairManager.prune(cc_pair_1, user_performing_action=admin_user)
            CCPairManager.wait_for_prune(
                cc_pair_1, now, timeout=60, user_performing_action=admin_user
            )

            selected_cc_pair = CCPairManager.get_indexing_status_by_id(
                cc_pair_1.id, user_performing_action=admin_user
            )
            assert selected_cc_pair is not None, "cc_pair not found after pruning!"
            assert selected_cc_pair.docs_indexed == 12

            # check vespa
            root_id = f"http://{hostname}:{port}/"
            index_id = f"http://{hostname}:{port}/index.html"
            about_id = f"http://{hostname}:{port}/about.html"
            courses_id = f"http://{hostname}:{port}/courses.html"

            doc_ids = [root_id, index_id, about_id, courses_id]
            retrieved_docs_dict = vespa_client.get_documents_by_id(doc_ids)["documents"]
            retrieved_docs = {
                doc["fields"]["document_id"]: doc["fields"]
                for doc in retrieved_docs_dict
            }

            # verify root exists in Vespa
            retrieved_doc = retrieved_docs.get(root_id)
            assert retrieved_doc

            # verify index.html does not exist in Vespa since it is a duplicate of root
            retrieved_doc = retrieved_docs.get(index_id)
            assert not retrieved_doc

            # verify about and courses do not exist
            retrieved_doc = retrieved_docs.get(about_id)
            assert not retrieved_doc

            retrieved_doc = retrieved_docs.get(courses_id)
            assert not retrieved_doc
