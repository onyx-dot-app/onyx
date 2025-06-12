# Llama Stack Endpoint Testing

This script sets up and runs a Llama Stack server for testing purposes. It automatically installs dependencies, builds the server, starts it, and performs a test chat completion request.

## Prerequisites

### System Requirements
- **Python 3.12** with pip installed
- **Linux/macOS** (recommended)
- **Internet connection** for downloading dependencies
- **Llama API Key** from Meta

### Required Tools
The script will automatically install these tools, but you can install them manually if needed:
- `uv` - Fast Python package installer and resolver
- `requests` - HTTP library for Python
- `llama-stack` - Llama Stack framework

## Installation

### 1. Get Your Llama API Key
You need a Llama API key from Meta. Visit [Meta's Llama website](https://llama.meta.com/) to obtain your API key.

### 2. Clone/Download the Script
Ensure you have the `llama_stack_endpoint_testing.py` file in your working directory.

### 3. Make the Script Executable (Optional)
```bash
chmod +x llama_stack_endpoint_testing.py
```

## Usage

### Basic Usage (Required)
```bash
python llama_stack_endpoint_testing.py --api-key YOUR_LLAMA_API_KEY
```

### Command Line Options
- `--api-key`: Your Llama API key (required)
- `--help`: Show help message and exit

## What the Script Does

1. **Environment Setup**
   - Cleans up UV_SYSTEM_PYTHON environment variable
   - Sets up the Llama API key from the required command line argument

2. **Dependency Installation**
   - Installs `uv` package manager
   - Installs `requests` library
   - Builds Llama Stack with the `llama_api` template

3. **Server Management**
   - Starts the Llama Stack server in the background
   - Waits for the server to become ready (up to 30 seconds)
   - Logs server output to `llama_stack_server.log`

4. **Testing**
   - Creates a Llama Stack client
   - Sends a test chat completion request
   - Displays the response from the server

5. **Cleanup**
   - Keeps the server running until interrupted
   - Gracefully shuts down the server on Ctrl+C

## Server Details

- **URL**: `http://0.0.0.0:8321`
- **Health Check**: `http://0.0.0.0:8321/v1/health`
- **Model**: `meta-llama/Llama-3.3-70B-Instruct`
- **Log File**: `llama_stack_server.log`

## Troubleshooting

### Server Won't Start
1. Check if port 8321 is already in use:
   ```bash
   lsof -i :8321
   ```

2. Kill existing processes using the port:
   ```bash
   python -c "from llama_stack_endpoint_testing import kill_llama_stack_server; kill_llama_stack_server()"
   ```

### API Key Issues
- Ensure your API key is valid and active
- The API key must be provided via the `--api-key` command line argument

### Installation Problems
- Ensure you have Python 3.12+ installed
- Check your internet connection
- Try running with `--verbose` flag for more detailed output

### Permission Errors
- On some systems, you might need to use `sudo` for package installation
- Consider using a Python virtual environment

## Manual Cleanup

If the script doesn't shut down properly, you can manually kill the server:

```bash
# Method 1: Using the built-in function
python -c "from llama_stack_endpoint_testing import kill_llama_stack_server; kill_llama_stack_server()"

# Method 2: Kill by port
lsof -ti:8321 | xargs kill -9

# Method 3: Kill by process name
pkill -f "llama.*stack.*run"
```

## Example Output

```
Using API key from command line argument
Installing uv...
Installing requests...
Building Llama Stack with dependencies...
Starting Llama Stack server...
Starting Llama Stack server with PID: 12345
Waiting for server to start.....
Server is ready!
Llama Stack server is running successfully!
Server process PID: 12345
Server is available at: http://0.0.0.0:8321
fetching a response from the server
Here is the response from the server:
Llamas graze peacefully in mountain meadows high,
Their gentle eyes reflect the endless sky.
Press Ctrl+C to stop the server...
```

## Files Created

- `llama_stack_server.log` - Server output and error logs
- Various cache and build files in `.llama_stack/` directory

## Support

For issues related to:
- **Llama Stack**: Visit the [Llama Stack GitHub repository](https://github.com/meta-llama/llama-stack)
- **API Keys**: Contact Meta support
- **This Script**: Check the troubleshooting section above
