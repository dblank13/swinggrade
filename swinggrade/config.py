"""Runtime configuration from environment variables (see .env.example)."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("SG_DATA_DIR", ROOT / "data"))
WORK_DIR = Path(os.getenv("SG_WORK_DIR", ROOT / "work"))
WEB_DIR = ROOT / "web"

# Pose backend: auto (Modal if available and under budget, else local CPU) | modal | local
POSE_BACKEND = os.getenv("POSE_BACKEND", "auto")
LOCAL_POSE_MODE = os.getenv("LOCAL_POSE_MODE", "balanced")  # rtmlib: lightweight|balanced|performance
MAX_HEIGHT = int(os.getenv("MAX_HEIGHT", "720"))
MAX_CLIP_SECONDS = float(os.getenv("MAX_CLIP_SECONDS", "12"))
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "200"))
UPLOAD_TTL_MIN = int(os.getenv("UPLOAD_TTL_MIN", "60"))

# Modal (free Starter plan includes $30/month of compute credit)
MODAL_APP = os.getenv("MODAL_APP", "swinggrade-pose")
MODAL_GPU = os.getenv("MODAL_GPU", "L4")
MODAL_MONTHLY_BUDGET_USD = float(os.getenv("MODAL_MONTHLY_BUDGET_USD", "25"))
MODAL_SCALEDOWN_S = int(os.getenv("MODAL_SCALEDOWN_S", "15"))
# Per-second list prices (modal.com/pricing, checked Oct 2026). Verify before relying on them.
MODAL_GPU_RATES = {"T4": 0.000164, "L4": 0.000222, "A10": 0.000306, "A10G": 0.000306, "L40S": 0.000542}
MODAL_CPU_CORE_RATE = 0.0000131
MODAL_MEM_GIB_RATE = 0.00000222
MODAL_CPU_CORES = 2
MODAL_MEM_GIB = 4
