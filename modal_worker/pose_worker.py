"""Modal GPU worker: decode the uploaded clip and run RTMPose (via rtmlib).

Deploy once from the project root (after `modal token new`):
    MODAL_GPU=L4 modal deploy modal_worker/pose_worker.py

Cost control for the free Starter plan ($30/month credit):
  * scales to zero; idle window is short (MODAL_SCALEDOWN_S, default 15 s)
  * max_containers=1 so a burst of uploads can't fan out across many GPUs
  * set a hard workspace spending limit in the Modal dashboard as a backstop
"""
import os
from pathlib import Path

import modal

GPU = os.environ.get("MODAL_GPU", "L4")
SCALEDOWN = int(os.environ.get("MODAL_SCALEDOWN_S", "15"))
POSE_MODE = os.environ.get("MODAL_POSE_MODE", "balanced")
HERE = Path(__file__).resolve().parent


def _download_models():
    import posecore
    posecore.make_estimator(device="cpu", mode=POSE_MODE)  # caches ONNX files in the image


image = (
    modal.Image.from_registry("nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04", add_python="3.11")
    .apt_install("ffmpeg", "libgl1", "libglib2.0-0")
    .pip_install("rtmlib==0.0.16", "onnxruntime-gpu==1.20.1", "opencv-python-headless", "numpy<2.3")
    .env({"MODAL_POSE_MODE": POSE_MODE})
    .add_local_file(HERE.parent / "swinggrade" / "posecore.py", "/root/posecore.py", copy=True)
    .run_function(_download_models)
)

app = modal.App("swinggrade-pose", image=image)


@app.cls(gpu=GPU, cpu=2, memory=4096, timeout=300, scaledown_window=SCALEDOWN, max_containers=1)
class Pose:
    @modal.enter()
    def load(self):
        import onnxruntime as ort
        import posecore
        self.provider = "CUDA" if "CUDAExecutionProvider" in ort.get_available_providers() else "CPU"
        self.est = posecore.make_estimator(device="cuda" if self.provider == "CUDA" else "cpu", mode=POSE_MODE)

    @modal.method()
    def infer(self, video: bytes, max_height: int = 720, max_seconds: float = 12.0) -> dict:
        import tempfile
        import posecore
        with tempfile.NamedTemporaryFile(suffix=".mov") as f:
            f.write(video)
            f.flush()
            r = posecore.run_pose(f.name, estimator=self.est, max_height=max_height, max_seconds=max_seconds)
        r["provider"] = f"{GPU}/{self.provider}"
        return r
