import argparse
import os
import subprocess
import sys
import time

from llama_stack_client import LlamaStackClient


def run_llama_stack_server_background():
    log_file = open("llama_stack_server.log", "w")
    process = subprocess.Popen(
        "uv run --with llama-stack llama stack run llama_api --image-type venv",
        shell=True,
        stdout=log_file,
        stderr=log_file,
        text=True,
    )

    print(f"Starting Llama Stack server with PID: {process.pid}")
    return process


def wait_for_server_to_start():
    import time

    import requests
    from requests.exceptions import ConnectionError

    url = "http://0.0.0.0:8321/v1/health"
    max_retries = 30
    retry_interval = 1

    print("Waiting for server to start", end="")
    for _ in range(max_retries):
        try:
            response = requests.get(url)
            if response.status_code == 200:
                print("\nServer is ready!")
                return True
        except ConnectionError:
            print(".", end="", flush=True)
            time.sleep(retry_interval)

    print("\nServer failed to start after", max_retries * retry_interval, "seconds")
    return False


# use this helper if needed to kill the server
def kill_llama_stack_server():
    # Kill any existing llama stack server processes
    try:
        # First try to find processes by port
        result = subprocess.run(["lsof", "-ti:8321"], capture_output=True, text=True)
        if result.stdout.strip():
            pids = result.stdout.strip().split("\n")
            for pid in pids:
                if pid:
                    print(f"Killing process {pid}")
                    subprocess.run(["kill", "-9", pid])

        # Also try to kill by process name pattern
        result = subprocess.run(
            ["pgrep", "-f", "llama.*stack.*run"], capture_output=True, text=True
        )
        if result.stdout.strip():
            pids = result.stdout.strip().split("\n")
            for pid in pids:
                if pid:
                    print(f"Killing llama stack process {pid}")
                    subprocess.run(["kill", "-9", pid])

    except Exception as e:
        print(f"Error killing server: {e}")
        # Fallback to the original method but with better error handling
        os.system("pkill -f 'llama.*stack.*run' 2>/dev/null || true")


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Set up and run the Llama Stack server"
    )
    parser.add_argument(
        "--api-key",
        type=str,
        required=True,
        help="Llama API key (required)",
    )
    return parser.parse_args()


def main():
    """Main function to set up and run the Llama Stack server."""
    args = parse_args()
    try:
        # Clean up UV_SYSTEM_PYTHON environment variable if present
        if "UV_SYSTEM_PYTHON" in os.environ:
            del os.environ["UV_SYSTEM_PYTHON"]

        # Set LLAMA_API_KEY from required command line argument
        os.environ["LLAMA_API_KEY"] = args.api_key
        print("Using API key from command line argument")

        print("Installing uv...")
        subprocess.run([sys.executable, "-m", "pip", "install", "uv"], check=True)

        print("Installing requests...")
        subprocess.run(["uv", "pip", "install", "requests"], check=True)

        print("Building Llama Stack with dependencies...")
        subprocess.run(
            [
                "uv",
                "run",
                "--with",
                "llama-stack",
                "llama",
                "stack",
                "build",
                "--template",
                "llama_api",
                "--image-type",
                "venv",
            ],
            check=True,
        )

        print("Starting Llama Stack server...")
        server_process = run_llama_stack_server_background()

        if wait_for_server_to_start():
            print("Llama Stack server is running successfully!")
            print("Server process PID:", server_process.pid)
            print("Server is available at: http://0.0.0.0:8321")
            client = LlamaStackClient(
                base_url="http://0.0.0.0:8321",
                provider_data={"llama_api_key": os.environ["LLAMA_API_KEY"]},
            )
            model_id = "meta-llama/Llama-3.3-70B-Instruct"
            print("fetching a response from the server")
            response = client.inference.chat_completion(
                model_id=model_id,
                messages=[
                    {"role": "system", "content": "You are a friendly assistant."},
                    {
                        "role": "user",
                        "content": "Write a two-sentence poem about llama.",
                    },
                ],
            )
            print("Here is the response from the server:")
            print(response.completion_message.content)
            return server_process
        else:
            print("Failed to start server")
            return None

    except subprocess.CalledProcessError as e:
        print(f"Error during setup: {e}")
        return None
    except Exception as e:
        print(f"Unexpected error: {e}")
        return None


if __name__ == "__main__":
    server_process = main()
    if server_process:
        try:
            # Keep the script running while server is active
            print("Press Ctrl+C to stop the server...")
            server_process.wait()
        except KeyboardInterrupt:
            print("\nShutting down server...")
            kill_llama_stack_server()
            print("Server stopped.")
