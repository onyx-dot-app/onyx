#!/bin/bash
set -euo pipefail

work_dir="$(mktemp -d)"
trap 'rm -rf "$work_dir"' EXIT
export CRAFT_SMOKE_DIR="$work_dir"

for tool in python pip node npm npx uv uvx gh git curl rg jq zip unzip zstd \
    agent-browser Xvfb xvfb-run certutil soffice pdftoppm pdfinfo fc-match; do
    command -v "$tool" >/dev/null
done
for removed in onyx-cli opencode bun iptables gosu corepack; do
    if command -v "$removed" >/dev/null; then
        echo "Unexpected legacy tool: $removed" >&2
        exit 1
    fi
done
test ! -e /usr/local/lib/node_modules/corepack
test ! -e /workspace/user_library
test ! -e /workspace/attachments
test ! -e /opt/onyx/runtime.json
command -v "${AGENT_BROWSER_EXECUTABLE_PATH:?Browser path must be set}" >/dev/null
"$AGENT_BROWSER_EXECUTABLE_PATH" --version
python -m pip check
agent-browser --version
uv --version
gh --version
fc-match Carlito
python - <<'PY'
import os
from pathlib import Path

import cryptography
import defusedxml
import lxml.etree
import matplotlib
import numpy as np
import pandas as pd
import pdfplumber
import requests
from docx import Document
from PIL import Image
from pptx import Presentation

matplotlib.use("Agg")
import matplotlib.pyplot as plt

work = Path(os.environ["CRAFT_SMOKE_DIR"])
document = Document()
document.add_paragraph("Craft runtime document conversion")
document.save(str(work / "document.docx"))
pd.DataFrame({"value": np.array([1, 2, 3])}).to_excel(work / "sheet.xlsx", index=False)
assert pd.read_excel(work / "sheet.xlsx")["value"].tolist() == [1, 2, 3]
for template in Path("/workspace/templates/pptx").glob("*.pptx"):
    assert len(Presentation(str(template)).slides) > 0
presentation = Presentation()
presentation.slides.add_slide(presentation.slide_layouts[0])
presentation.save(str(work / "python-slides.pptx"))
plt.plot([1, 2, 3])
plt.savefig(work / "chart.png")
with Image.open(work / "chart.png") as image:
    assert image.width > 0
PY
node <<'JS'
const fs = require('fs');
const path = require('path');
const PptxGenJS = require('pptxgenjs');
const sharp = require('sharp');
(async () => {
    const work = process.env.CRAFT_SMOKE_DIR;
    const svg = '/opt/onyx/assets/icons/lucide/icons/circle-check.svg';
    const tablerSvg = '/opt/onyx/assets/icons/tabler/icons/outline/shield-check.svg';
    fs.accessSync(tablerSvg);
    fs.accessSync('/opt/onyx/assets/icons/lucide/LICENSE');
    fs.accessSync('/opt/onyx/assets/icons/tabler/LICENSE');
    const png = path.join(work, 'icon.png');
    await sharp(svg).resize(128).png().toFile(png);
    await sharp(tablerSvg).resize(128).png().toFile(path.join(work, 'tabler.png'));
    const deck = new PptxGenJS();
    deck.addSlide().addImage({path: png, x: 1, y: 1, w: 1, h: 1});
    await deck.writeFile({fileName: path.join(work, 'node-slides.pptx')});
})().catch(error => { console.error(error); process.exit(1); });
JS

timeout --kill-after=10s 90 soffice "-env:UserInstallation=file://$work_dir/lo-profile" \
    --headless --convert-to pdf --outdir "$work_dir" \
    "$work_dir/document.docx" "$work_dir/sheet.xlsx" "$work_dir/node-slides.pptx"
for name in document sheet node-slides; do
    test -s "$work_dir/$name.pdf"
    pdfinfo "$work_dir/$name.pdf" >/dev/null
done
pdftoppm -f 1 -singlefile -scale-to 200 -png "$work_dir/document.pdf" "$work_dir/preview"
test -s "$work_dir/preview.png"

guest_html=/tmp/craft-runtime-browser-$$.html
trap 'rm -rf "$work_dir"; rm -f "$guest_html"' EXIT
printf '<html><body>craft-browser-ready</body></html>' > "$guest_html"
chmod 0644 "$guest_html"
# shellcheck disable=SC2016
timeout --kill-after=10s 60 runuser -u sandbox -- xvfb-run -a bash -c '
    set -euo pipefail
    export AGENT_BROWSER_HEADED=true AGENT_BROWSER_ALLOW_FILE_ACCESS=true
    trap "agent-browser --session craft-runtime-smoke close" EXIT
    agent-browser --session craft-runtime-smoke open "file://$1"
    agent-browser --session craft-runtime-smoke get text body | rg -q craft-browser-ready
' bash "$guest_html"
printf 'Craft runtime smoke checks passed.\n'
