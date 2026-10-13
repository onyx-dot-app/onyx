"""Verify loopback HTTP bypasses the sandbox proxy with the deployed environment."""

LOCAL_HTTP_PROBE: str = """
import http.server, socket, subprocess, sys, threading
host = sys.argv[1]
class Server(http.server.HTTPServer):
    address_family = socket.AF_INET6 if ":" in host else socket.AF_INET
class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"sandbox loopback verified")
    def log_message(self, *args):
        pass
with Server((host, 0), Handler) as server:
    threading.Thread(target=server.serve_forever, daemon=True).start()
    authority = "[" + host + "]" if ":" in host else host
    try:
        subprocess.run(["curl", "--fail", "--silent", "--show-error", "--max-time", "10",
                        f"http://{authority}:{server.server_port}/"], check=True)
    finally:
        server.shutdown()
"""
