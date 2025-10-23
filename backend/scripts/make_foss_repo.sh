#!/usr/bin/env bash
set -euo pipefail

echo "=== Building FOSS mirror ==="
rm -rf /tmp/foss && mkdir -p /tmp/foss
git clone --mirror . /tmp/foss/.git
cd /tmp/foss

echo "=== Creating MIT license file ==="
cat > /tmp/mit_license.txt << 'EOF'
Copyright (c) 2023-present DanswerAI, Inc.

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
EOF

echo "=== Creating blob callback script ==="
cat > /tmp/license_replacer.py << 'PYEOF'
#!/usr/bin/env python3

# Read MIT license from file
with open('/tmp/mit_license.txt', 'rb') as f:
    MIT_LICENSE = f.read()

def replace_license(blob, metadata):
    if blob.original_path == b'LICENSE':
        blob.data = MIT_LICENSE

import git_filter_repo as fr

args = fr.FilteringOptions.parse_args(['--force'], error_on_empty=False)
filter = fr.RepoFilter(args, blob_callback=replace_license)
filter.run()
PYEOF

chmod +x /tmp/license_replacer.py

# NOTE: intentionally keeping the web/src/app/ee directory
# for now since there's no clean way to remove it
echo "=== Removing enterprise directory and licenses from history ==="
git filter-repo \
  --path backend/ee --invert-paths \
  --path backend/ee/LICENSE --invert-paths \
  --path web/src/app/ee/LICENSE --invert-paths \
  --force

echo "=== Replacing LICENSE file in all commits ==="
/tmp/license_replacer.py

echo "=== Checking out working tree ==="
git clone . ../foss_repo

echo "=== Done building FOSS repo ==="
