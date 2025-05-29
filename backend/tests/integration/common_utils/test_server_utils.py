import threading
from collections.abc import Generator
from contextlib import contextmanager
from time import sleep

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles


# FastAPI server for serving files
def create_fastapi_app(directory: str) -> FastAPI:
    """
    Creates a FastAPI application that serves static files from a given directory.
    """
    app = FastAPI()

    # Mount the directory to serve static files
    app.mount("/", StaticFiles(directory=directory, html=True), name="static")

    return app


@contextmanager
def fastapi_server_context(
    directory: str, port: int = 8000
) -> Generator[None, None, None]:
    """
    Context manager to run a FastAPI server in a separate thread.
    The server serves static files from the specified directory.
    """
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
