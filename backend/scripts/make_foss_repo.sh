#!/usr/bin/env bash
set -euo pipefail

echo "=== Building FOSS mirror ==="
mkdir -p /tmp/foss
git clone --mirror . /tmp/foss/.git
cd /tmp/foss

echo "=== Removing enterprise directory from history ==="
git filter-repo --path ee --invert-paths --force

echo "=== Checking out working tree ==="
git clone . ../foss_repo
cd ../foss_repo

echo "=== Applying MIT license ==="
cat > LICENSE << 'EOF'
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

echo "=== Done building FOSS repo ==="
