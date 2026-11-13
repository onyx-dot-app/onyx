#!/usr/bin/env bash
set -euo pipefail

# update-sandbox-browser.sh rewrites these pins by line shape: keep `version=`
# at column 0 and one `checksum=` in each architecture arm.
version=157.0.8103.78
case "$(dpkg --print-architecture)" in
  amd64)
    platform=linux64
    checksum=9223832977a13db3646201b1341c1f9cf08afa3ceae92540116d7b0c062364fb
    ;;
  arm64)
    platform=linux-arm64
    checksum=f354d666822a11d8fe99e923c44be77dd226fab2750c5b5947e6318818bf10f1
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
