"""
Nextcloud WebDAV client for accessing files and metadata.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, quote, unquote

import requests
from requests.auth import HTTPBasicAuth

# Import XML parsing with proper fallback handling
try:
    from defusedxml import ElementTree as ET
    from xml.etree.ElementTree import Element  # For type hints only
except ImportError:
    # Fallback to standard library with warning
    import xml.etree.ElementTree as ET
    from xml.etree.ElementTree import Element
    import warnings
    warnings.warn("defusedxml not available. Consider installing for better security: pip install defusedxml")

logger = logging.getLogger(__name__)


class NextcloudWebDAVClient:
    """Client for interacting with Nextcloud WebDAV API."""
    
    def __init__(
        self,
        server_url: str,
        username: str,
        password: str,
        verify_ssl: bool = True,
        root_path: Optional[str] = None,
    ) -> None:
        """Initialize the WebDAV client.
        
        Args:
            server_url: Base URL of the Nextcloud instance
            username: Nextcloud username
            password: Nextcloud password or app token
            verify_ssl: Whether to verify SSL certificates
        """
        self.server_url = server_url.rstrip("/")
        self.username = username
        self.password = password
        self.verify_ssl = verify_ssl
        self._root_path = (root_path or "").lstrip("/")
        
        # Construct WebDAV base URL - for WebDAV API access
        self.webdav_url = f"{self.server_url}/remote.php/dav/files/{username}/"
        
        # Setup session for connection reuse
        self.session = requests.Session()
        self.session.auth = HTTPBasicAuth(username, password)
        self.session.verify = verify_ssl
        
        # Set appropriate headers
        self.session.headers.update({
            "User-Agent": "Onyx-Nextcloud-Connector/1.0",
            "Content-Type": "application/xml; charset=utf-8",
        })

    def test_connection(self) -> bool:
        """Test if we can successfully connect to the Nextcloud instance.
        
        Returns:
            True if connection is successful, False otherwise
        """
        try:
            response = self.session.request(
                "PROPFIND",
                self.webdav_url,
                headers={"Depth": "0"},
                timeout=10,
            )
            
            # Check for successful response
            if response.status_code in [200, 207]:  # 207 is Multi-Status for WebDAV
                logger.info(f"Successfully connected to Nextcloud at {self.server_url}")
                return True
            elif response.status_code == 401:
                logger.error("Authentication failed - check username and password")
                return False
            elif response.status_code == 404:
                logger.error("WebDAV endpoint not found - check server URL")
                return False
            else:
                logger.error(f"Connection failed with status {response.status_code}: {response.text}")
                return False
                
        except requests.exceptions.SSLError as e:
            logger.error(f"SSL certificate verification failed: {e}")
            logger.error("Consider setting verify_ssl=False for self-signed certificates")
            return False
        except requests.exceptions.ConnectionError as e:
            logger.error(f"Failed to connect to server: {e}")
            return False
        except requests.exceptions.Timeout as e:
            logger.error(f"Connection timed out: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error during connection test: {e}")
            return False

    def list_files(
        self,
        path: str = "",
        depth: str = "infinity",
        modified_since: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """List files and directories in the specified path.
        
        Args:
            path: Path relative to user's root directory
            depth: WebDAV depth ('0', '1', or 'infinity')
            modified_since: Only return files modified after this datetime
            
        Returns:
            List of file/directory information dictionaries
        """
        url = urljoin(self.webdav_url, quote(path.lstrip("/")))
        
        # Build PROPFIND request body to get file properties
        propfind_body = """<?xml version="1.0" encoding="UTF-8"?>
<d:propfind xmlns:d="DAV:" xmlns:oc="http://owncloud.org/ns" xmlns:nc="http://nextcloud.org/ns">
  <d:prop>
    <d:getlastmodified />
    <d:getetag />
    <d:getcontenttype />
    <d:resourcetype />
    <d:getcontentlength />
    <oc:fileid />
    <oc:permissions />
    <oc:size />
    <oc:owner-display-name />
    <d:displayname />
  </d:prop>
</d:propfind>"""

        try:
            response = self.session.request(
                "PROPFIND",
                url,
                data=propfind_body,
                headers={"Depth": depth},
                timeout=30,
            )
            response.raise_for_status()
            
            logger.debug(f"WebDAV PROPFIND request successful")
            logger.debug(f"Response status: {response.status_code}")
            logger.debug(f"Response length: {len(response.text)} characters")
            logger.debug(f"Request URL: {url}")
            
            # Parse XML response
            files = self._parse_propfind_response(response.text, modified_since)
            logger.debug(f"Parsed {len(files)} items from XML response")
            return files
            
        except Exception as e:
            logger.error(f"Failed to list files at path '{path}': {e}")
            raise

    def get_file_content(self, file_path: str) -> bytes:
        """Download file content.
        
        Args:
            file_path: Path to the file relative to user's root directory
            
        Returns:
            File content as bytes
        """
        # Clean the file path and ensure proper encoding
        clean_path = file_path.lstrip("/")
        
        # Always URL-encode the path since it should be clean/decoded now
        url = urljoin(self.webdav_url, quote(clean_path))
        
        logger.debug(f"Requesting file from URL: {url}")
        
        try:
            response = self.session.get(url, timeout=60)
            response.raise_for_status()
            return response.content
        except Exception as e:
            logger.error(f"Failed to download file '{file_path}': {e}")
            raise

    def _parse_propfind_response(
        self, 
        xml_content: str, 
        modified_since: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """Parse WebDAV PROPFIND response XML.
        
        Args:
            xml_content: XML response content
            modified_since: Filter files modified after this datetime
            
        Returns:
            List of parsed file information
        """
        files = []
        
        try:
            # Parse XML with namespaces
            root = ET.fromstring(xml_content)
            
            # Debug: Show raw XML snippet
            logger.debug(f"Raw XML response snippet:")
            xml_lines = xml_content.split('\n')[:10]  # First 10 lines
            for i, line in enumerate(xml_lines):
                logger.debug(f"  {i+1:2d}: {line.strip()}")
            if len(xml_lines) >= 10:
                logger.debug(f"  ... (truncated, total {len(xml_content.split())} lines)")
            
            # Define namespaces
            namespaces = {
                'd': 'DAV:',
                'oc': 'http://owncloud.org/ns',
                'nc': 'http://nextcloud.org/ns'
            }
            
            # Process each response element
            for response in root.findall('.//d:response', namespaces):
                file_info = self._extract_file_info(response, namespaces)
                
                if file_info:
                    # Debug: Print first few files found
                    if len(files) < 3:
                        logger.debug(f"Found item: {file_info.get('href', 'no-href')} -> {file_info.get('path', 'no-path')}")
                        logger.debug(f"Is directory: {file_info.get('is_directory', 'unknown')}")
                        logger.debug(f"Size: {file_info.get('size', 'unknown')}")
                    
                    # Apply date filter if specified
                    if modified_since and file_info.get('last_modified'):
                        if file_info['last_modified'] < modified_since:
                            continue
                    
                    files.append(file_info)
                    
        except ET.ParseError as e:
            logger.error(f"Failed to parse XML response: {e}")
            raise
        except Exception as e:
            logger.error(f"Error processing PROPFIND response: {e}")
            raise
            
        return files

    def _extract_file_info(
        self, 
        response_elem: Element, 
        namespaces: Dict[str, str]
    ) -> Optional[Dict[str, Any]]:
        """Extract file information from a single response element.
        
        Args:
            response_elem: XML response element
            namespaces: XML namespace mappings
            
        Returns:
            File information dictionary or None if parsing fails
        """
        try:
            # Get href (file path)
            href_elem = response_elem.find('d:href', namespaces)
            if href_elem is None or not href_elem.text:
                return None
                
            href = href_elem.text
            
            # Extract properties
            propstat = response_elem.find('.//d:propstat[d:status="HTTP/1.1 200 OK"]', namespaces)
            if propstat is None:
                return None
                
            prop = propstat.find('d:prop', namespaces)
            if prop is None:
                return None

            # Parse file properties
            file_info = {
                'href': href,
                'path': self._clean_path(href),
                'is_directory': self._is_directory(prop, namespaces),
            }
            
            # Extract basic properties
            file_info.update(self._extract_basic_properties(prop, namespaces))
            
            # Extract Nextcloud-specific properties
            file_info.update(self._extract_nextcloud_properties(prop, namespaces))
            
            return file_info
            
        except Exception as e:
            logger.warning(f"Failed to extract file info from response element: {e}")
            return None

    def _extract_basic_properties(
        self, 
        prop_elem: Element, 
        namespaces: Dict[str, str]
    ) -> Dict[str, Any]:
        """Extract basic WebDAV properties."""
        properties = {}
        
        # Last modified
        lastmod_elem = prop_elem.find('d:getlastmodified', namespaces)
        if lastmod_elem is not None and lastmod_elem.text:
            try:
                # Parse RFC 2822 date format
                dt = datetime.strptime(lastmod_elem.text, '%a, %d %b %Y %H:%M:%S %Z')
                properties['last_modified'] = dt.replace(tzinfo=timezone.utc)
            except ValueError:
                logger.warning(f"Could not parse last modified date: {lastmod_elem.text}")
        
        # Content length (file size)
        length_elem = prop_elem.find('d:getcontentlength', namespaces)
        if length_elem is not None and length_elem.text:
            try:
                properties['size'] = int(length_elem.text)
            except ValueError:
                pass
        
        # Content type
        type_elem = prop_elem.find('d:getcontenttype', namespaces)
        if type_elem is not None and type_elem.text:
            properties['content_type'] = type_elem.text
        
        # ETag
        etag_elem = prop_elem.find('d:getetag', namespaces)
        if etag_elem is not None and etag_elem.text:
            properties['etag'] = etag_elem.text.strip('"')
        
        # Display name
        name_elem = prop_elem.find('d:displayname', namespaces)
        if name_elem is not None and name_elem.text:
            properties['name'] = name_elem.text
        
        return properties

    def _extract_nextcloud_properties(
        self, 
        prop_elem: Element, 
        namespaces: Dict[str, str]
    ) -> Dict[str, Any]:
        """Extract Nextcloud-specific properties."""
        properties = {}
        
        # File ID
        fileid_elem = prop_elem.find('oc:fileid', namespaces)
        if fileid_elem is not None and fileid_elem.text:
            properties['file_id'] = fileid_elem.text
        
        # Permissions
        perms_elem = prop_elem.find('oc:permissions', namespaces)
        if perms_elem is not None and perms_elem.text:
            properties['permissions'] = perms_elem.text
        
        # Size (alternative to content length)
        size_elem = prop_elem.find('oc:size', namespaces)
        if size_elem is not None and size_elem.text:
            try:
                properties['oc_size'] = int(size_elem.text)
            except ValueError:
                pass
        
        # Owner
        owner_elem = prop_elem.find('oc:owner-display-name', namespaces)
        if owner_elem is not None and owner_elem.text:
            properties['owner'] = owner_elem.text
        
        return properties

    def _is_directory(self, prop_elem: Element, namespaces: Dict[str, str]) -> bool:
        """Check if the item is a directory."""
        resourcetype = prop_elem.find('d:resourcetype', namespaces)
        if resourcetype is not None:
            collection = resourcetype.find('d:collection', namespaces)
            return collection is not None
        return False

    def _clean_path(self, href: str) -> str:
        """Clean and normalize the file path."""
        # Remove WebDAV prefix and decode
        path = href
        
        logger.debug(f"Cleaning path: '{href}'")
        
        # Try different WebDAV prefix formats
        webdav_prefixes = [
            f"/remote.php/dav/files/{self.username}/",
            f"remote.php/dav/files/{self.username}/",
            f"/{self.username}/",
            f"{self.username}/",
        ]
        
        for prefix in webdav_prefixes:
            if path.startswith(prefix):
                path = path[len(prefix):]
                logger.debug(f"Removed prefix '{prefix}' -> '{path}'")
                break
        
        # URL-decode the path to handle spaces and special characters
        path = unquote(path)
        logger.debug(f"URL decoded path: '{path}'")
        
        # Ensure it starts with /
        if not path.startswith("/"):
            path = "/" + path
        
        # Handle root directory case
        if path == "/":
            path = "/"
        
        logger.debug(f"Final cleaned path: '{path}'")
        return path
