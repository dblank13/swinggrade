#!/bin/sh
# Download the browser (MediaPipe) and server (RTMPose) pose models.
# Used by setup.sh and the Dockerfile. Safe to re-run.
set -eu
cd "$(dirname "$0")/.."
V=1.0.1
base="https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@$V"
mkdir -p web/vendor/tasks-vision/wasm web/vendor/models
curl -fsSL "$base/vision_bundle.mjs" -o web/vendor/tasks-vision/vision_bundle.mjs
for f in vision_wasm_internal.js vision_wasm_internal.wasm vision_wasm_nosimd_internal.js \
         vision_wasm_nosimd_internal.wasm vision_wasm_module_internal.js vision_wasm_module_internal.wasm; do
  curl -fsSL "$base/wasm/$f" -o "web/vendor/tasks-vision/wasm/$f" || echo "optional $f not found"
done
for m in lite full; do
  curl -fsSL "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_$m/float16/latest/pose_landmarker_$m.task" \
    -o "web/vendor/models/pose_landmarker_$m.task"
done
python - <<'EOF'
import os
from swinggrade import posecore
posecore.make_estimator(device="cpu", mode=os.getenv("LOCAL_POSE_MODE", "balanced"))
print("RTMPose models cached")
EOF
