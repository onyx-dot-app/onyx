"""HTTP and CONNECT probe run inside a sandbox with its deployed proxy settings."""

PROXY_PROBE = """
import http.client, json, os, socket, sys
from urllib.parse import urlsplit
spec = json.loads(sys.argv[1])
proxy = urlsplit(os.environ['HTTP_PROXY']) if not spec.get('local') else None
peer = (proxy.hostname, proxy.port or 8080) if proxy else (spec['local'], spec['proxy_port'])
authority = ('[' + spec['host'] + ']' if ':' in spec['host'] else spec['host']) + ':' + str(spec['port'])
target = authority if spec['method'] == 'CONNECT' else spec.get('scheme', 'http') + '://' + authority + spec.get('path', '/')
with socket.create_connection(peer, timeout=15) as connection:
    connection.settimeout(15)
    connection.sendall((spec['method'] + ' ' + target + ' HTTP/1.1\\r\\nHost: ' + authority + '\\r\\nConnection: close\\r\\n\\r\\n').encode())
    response = http.client.HTTPResponse(connection)
    response.begin()
    body = b'' if spec['method'] == 'CONNECT' and response.status == 200 else response.read()
    print(json.dumps({'status': response.status, 'body': body.decode(errors='replace')}))
"""
