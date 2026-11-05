#!/usr/bin/env bash
set -euo pipefail

# Update the version and both archive hashes together.
version=157.0.8103.38
case "$(dpkg --print-architecture)" in
  amd64)
    platform=linux64
    checksum=8cdeb344e9b2cefe59f4aea8d1d93d5d93054c03cde217665c16fc1f62e72a66
    ;;
  arm64)
    platform=linux-arm64
    checksum=5517510e61657ff43ee9ab804ecd1a499b3d5bd3caf72f097516bd6565ba5a17
    ;;
  *) echo 'Unsupported browser architecture' >&2; exit 1 ;;
esac

curl --fail --silent --show-error --location --retry 3 \
  "https://storage.googleapis.com/chrome-for-testing-public/${version}/${platform}/chrome-${platform}.zip" \
  --output /tmp/chrome.zip
printf '%s  /tmp/chrome.zip\n' "$checksum" | sha256sum --check -
unzip -q /tmp/chrome.zip -d /opt
mv "/opt/chrome-${platform}" /opt/chrome
rm /tmp/chrome.zip
/opt/chrome/chrome --version | grep -F " ${version} "

# ODS's Debian inventory cannot identify a ZIP install. Grype scans this
# explicit CPE inventory in the image audit resolver before ODS scans apt.
cat > /opt/chrome/browser.cdx.json <<EOF
{
  "bomFormat": "CycloneDX",
  "specVersion": "1.5",
  "version": 1,
  "components": [{
    "type": "application",
    "name": "chrome",
    "version": "${version}",
    "cpe": "cpe:2.3:a:google:chrome:${version}:*:*:*:*:*:*:*"
  }]
}
EOF
