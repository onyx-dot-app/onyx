#!/usr/bin/env bash
set -euo pipefail

# update-sandbox-browser.sh rewrites these pins by line shape: keep `version=`
# at column 0 and one `checksum=` in each architecture arm.
version=158.0.8127.88
case "$(dpkg --print-architecture)" in
  amd64)
    platform=linux64
    checksum=59e3b43f8b3aaa292238fbdcfb36a93127debd53e212510dcdc2cc8812b4b57e
    ;;
  arm64)
    platform=linux-arm64
    checksum=91669b5de79af808d498037dd974e4b09461776a1b5240b3bb656abd17e5d3ab
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
