#!/usr/bin/env bash
set -euo pipefail

echo "=== Building FOSS mirror ==="
rm -rf /tmp/foss_repo && mkdir -p /tmp/foss_repo
git clone . /tmp/foss_repo
cd /tmp/foss_repo

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

# NOTE: intentionally keeping the web/src/app/ee directory
# for now since there's no clean way to remove it
echo "=== Removing enterprise directory and licenses from history ==="
git filter-repo \
  --path backend/ee --invert-paths \
  --path backend/ee/LICENSE --invert-paths \
  --path web/src/app/ee/LICENSE --invert-paths \
  --force

# NOTE: not ideal, since this means every day folks with the repo
# locally will need to hard reset if they want to pull in more stuff.
echo "=== Recreating empty enterprise directory ==="
mkdir -p backend/ee
git add backend/ee
git commit -m "Add empty enterprise directory" --allow-empty

echo "=== Creating blob callback script ==="
cat > /tmp/license_replacer.py << 'PYEOF'
#!/usr/bin/env python3
import sys

# Read MIT license from file
with open('/tmp/mit_license.txt', 'rb') as f:
    MIT_LICENSE = f.read()

import git_filter_repo as fr

replaced_count = 0

def replace_license_blob_content(blob, metadata):
    """Replace LICENSE blob content with MIT license based on content detection"""
    global replaced_count

    # Check if this blob looks like a license file
    # We'll replace any blob that contains the old Apache/custom license text
    if blob.data and len(blob.data) > 100:
        # Check for license-like content
        # Unfortunately, we don't have access to the path, so we can't just check that the path
        # is `LICENSE`.
        data_lower = blob.data.lower()
        if (
            b'portions of this software are licensed as follows' in data_lower and
            b'all third party components incorporated into the' in data_lower
        ):
            # Additional check: make sure it's actually a license file, not source code
            # License files typically don't have common code patterns
            if b'def ' not in blob.data and b'class ' not in blob.data and b'import ' not in blob.data[:200]:
                blob.data = MIT_LICENSE
                replaced_count += 1

args = fr.FilteringOptions.parse_args(['--force'], error_on_empty=False)
filter_obj = fr.RepoFilter(args, blob_callback=replace_license_blob_content)
filter_obj.run()

print(f"Replaced {replaced_count} LICENSE blob(s)", file=sys.stderr)
PYEOF

echo "=== Replacing LICENSE file in all commits ==="
chmod +x /tmp/license_replacer.py
/tmp/license_replacer.py

echo "=== Done building FOSS repo ==="
