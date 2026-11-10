#!/usr/bin/env bash
set -euo pipefail

# .github/scripts/update-sandbox-browser.sh rewrites the version and both
# archive hashes together.
version=157.0.8103.50
case "$(dpkg --print-architecture)" in
  amd64)
    platform=linux64
    checksum=d17167bc092eb495a3b768c7467f27e35f625aa03834233a1663af67dcb668c9
    ;;
  arm64)
    platform=linux-arm64
    checksum=9539c1612121eb09c4b787f4f9d0c732357772eb22583620ffed64d50dd6c4cc
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
