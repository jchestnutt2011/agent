"""Local speech-to-text via faster-whisper, GPU-accelerated. Not a chat
tool (no SCHEMA/run) — this is UI plumbing used directly by app.py to turn a
recording from st.audio_input into text, which then goes through the exact
same chat pipeline as typed input.

Runs entirely on-device (no cloud STT API) to match this project's whole
point: private, self-hosted, using the GPU that's already sitting there.
"""

import io
import os
import sys

# ctranslate2 (faster-whisper's inference engine) needs CUDA's cuBLAS/cuDNN
# DLLs on the search path. The nvidia-cublas-cu12/nvidia-cudnn-cu12 pip
# packages ship them but don't register them anywhere Windows looks by
# default, so this has to happen before faster_whisper (and therefore
# ctranslate2) is imported.
def _register_cuda_dll_dirs():
    site_packages = os.path.join(os.path.dirname(sys.executable), "..", "Lib", "site-packages")
    for pkg in ("cublas", "cudnn", "cuda_nvrtc"):
        bin_dir = os.path.abspath(os.path.join(site_packages, "nvidia", pkg, "bin"))
        if os.path.isdir(bin_dir):
            os.add_dll_directory(bin_dir)
            os.environ["PATH"] = bin_dir + os.pathsep + os.environ["PATH"]


_register_cuda_dll_dirs()

from faster_whisper import WhisperModel  # noqa: E402  (must follow DLL setup)

# This GPU is Pascal-generation (GTX 1080 Ti) and doesn't have fast FP16
# tensor cores anyway, and float16 compute isn't even available without a
# full cuDNN optimized-kernel install — int8_float32 is both what's
# supported here and a sensible speed/accuracy tradeoff for this hardware.
MODEL_SIZE = "small.en"
COMPUTE_TYPE = "int8_float32"
DEVICE = "cuda"

_model = None


def _get_model():
    global _model
    if _model is None:
        _model = WhisperModel(MODEL_SIZE, device=DEVICE, compute_type=COMPUTE_TYPE)
    return _model


def transcribe(audio_bytes):
    """Transcribe WAV audio bytes (as produced by st.audio_input) to text.
    Returns '' on empty/silent audio or any transcription failure — never
    raises, since a bad recording shouldn't crash the chat UI, just produce
    no text for the caller to notice and handle."""
    if not audio_bytes:
        return ""
    try:
        model = _get_model()
        segments, _ = model.transcribe(io.BytesIO(audio_bytes), beam_size=5)
        return " ".join(segment.text.strip() for segment in segments).strip()
    except Exception:
        return ""
