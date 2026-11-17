#!/usr/bin/env sh
# Baut die statische Live-Demo zusammen: demo/ + 3D-Viewer + Logo -> Zielordner (Standard: _site).
# Wird vom Workflow .github/workflows/pages.yml genutzt; lokal z. B.:
#   sh scripts/assemble_demo.sh .cache/site && python -m http.server 8510 --directory .cache/site
set -e
OUT="${1:-_site}"
rm -rf "$OUT"
mkdir -p "$OUT/viewer" "$OUT/assets"
cp -r demo/. "$OUT/"
cp modules/viewer_webgpu/frontend/index.html modules/viewer_webgpu/frontend/*.js "$OUT/viewer/"
cp assets/icon.svg assets/logo.svg "$OUT/assets/"
touch "$OUT/.nojekyll"
echo "Live-Demo in $OUT: $(find "$OUT" -type f | wc -l) Dateien"
