"""Shared Hailo-8 scheduler and relative-depth inference."""
from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
import cv2
import numpy as np


class HailoNetworks:
    def __init__(self):
        self.stack = ExitStack()
        self.device = None
        self.networks = {}

    def open(self, path):
        if path in self.networks:
            return self.networks[path]
        from hailo_platform import (ConfigureParams, FormatType, HailoSchedulingAlgorithm,
                                    HailoStreamInterface, HEF, InferVStreams,
                                    InputVStreamParams, OutputVStreamParams, VDevice)
        if not Path(path).is_file():
            raise FileNotFoundError(f'Hailoモデルが見つかりません: {path}')
        if self.device is None:
            params = VDevice.create_params()
            params.scheduling_algorithm = HailoSchedulingAlgorithm.ROUND_ROBIN
            self.device = self.stack.enter_context(VDevice(params))
        hef = HEF(path)
        group = self.device.configure(hef, ConfigureParams.create_from_hef(hef, HailoStreamInterface.PCIe))[0]
        infer = self.stack.enter_context(InferVStreams(
            group, InputVStreamParams.make(group, format_type=FormatType.UINT8),
            OutputVStreamParams.make(group, format_type=FormatType.FLOAT32)))
        self.networks[path] = (hef, infer)
        return hef, infer

    def close(self):
        self.stack.close()
        self.device = None
        self.networks.clear()


class HailoDepthAnalysis:
    def __init__(self, networks, depth_path):
        self.networks = networks
        self.depth_path = depth_path
        self.depth_ms = None
        self.depth_values = None

    def depth(self, frame):
        hef, infer = self.networks.open(self.depth_path)
        info = hef.get_input_vstream_infos()[0]
        h, w, _ = info.shape
        image = cv2.cvtColor(cv2.resize(frame, (w, h)), cv2.COLOR_BGR2RGB)
        result = infer.infer({info.name: image[None]})
        values = np.squeeze(next(iter(result.values())))
        if values.ndim != 2 or not np.isfinite(values).all():
            raise ValueError('深度モデルの出力が不正です')
        # SCDepthV3 HEF outputs logits. Hailo Model Zoo's postprocess uses
        # 1 / (sigmoid(logits) * 10 + .009): larger logits mean nearer.
        # Keep raw logits for same-frame ordering, never normalize per frame.
        self.depth_values = values.copy()
        self.depth_ms = infer.get_hw_time() * 1000
