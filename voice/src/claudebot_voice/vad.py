"""Silero VAD v5 on onnxruntime, one 512-sample frame (32 ms at 16 kHz) at a time."""

import numpy as np
import onnxruntime as ort

from .config import MODELS

FRAME = 512
CONTEXT = 64


class SileroVAD:
    def __init__(self, path=MODELS / "silero_vad.onnx"):
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 1
        opts.inter_op_num_threads = 1
        self.session = ort.InferenceSession(str(path), sess_options=opts, providers=["CPUExecutionProvider"])
        self.sr = np.array(16000, dtype=np.int64)
        self.reset()

    def reset(self):
        self.state = np.zeros((2, 1, 128), dtype=np.float32)
        self.context = np.zeros((1, CONTEXT), dtype=np.float32)

    def __call__(self, frame: np.ndarray) -> float:
        """Speech probability for one frame of float32 samples in [-1, 1]."""
        x = np.concatenate([self.context, frame.reshape(1, FRAME)], axis=1)
        out, self.state = self.session.run(None, {"input": x, "state": self.state, "sr": self.sr})
        self.context = x[:, -CONTEXT:]
        return float(out[0][0])
