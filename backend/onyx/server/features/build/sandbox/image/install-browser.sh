#!/usr/bin/env bash
set -euo pipefail

# update-sandbox-browser.sh rewrites these pins by line shape: keep `version=`
# at column 0 and one `checksum=` in each architecture arm.
version=158.0.8127.36
case "$(dpkg --print-architecture)" in
  amd64)
    platform=linux64
    checksum=dba9cc838e1ce269c33ea68170881127bd15d078fc3ca5891c90802819a4d7c7
    ;;
  arm64)
    platform=linux-arm64
    checksum=f811b64a50cbc73f94fda7b3f3b3bf62be5d9409b3207e6ead9b61e6706afffe
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
# explicit CPE inventory through ODS alongside the apt scan.
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
