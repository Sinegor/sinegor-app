#!/usr/bin/env bash
set -euo pipefail
SINEGOR_LED_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export OCIO="$SINEGOR_LED_DIR/srgb.ocio"
if command -v blender >/dev/null 2>&1; then
  SINEGOR_BLENDER=(blender)
elif command -v flatpak >/dev/null 2>&1 && flatpak info org.blender.Blender >/dev/null 2>&1; then
  SINEGOR_BLENDER=(flatpak run "--env=OCIO=$OCIO" org.blender.Blender)
else
  echo 'Blender is not installed. Supply Blender 5.1.1 and run generate.py as described in README.' >&2
  exit 1
fi
if [[ "${1:-}" == '--open' ]]; then
  exec "${SINEGOR_BLENDER[@]}" "$SINEGOR_LED_DIR/output/SINEGOR_LAB.blend"
fi
exec "${SINEGOR_BLENDER[@]}" --background --factory-startup --python-exit-code 1 \
  --python "$SINEGOR_LED_DIR/generate.py" -- "$@"
