"""IPM bird's-eye lane detector for the Plan A lane pipeline.

The detector separates expensive global acquisition from cheap local tracking.
It intentionally returns no lane when confidence is insufficient; callers must
not turn an absent lane marking into an LDW decision.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from src.types import LaneInfo
from src.utils.geometry import line_intersection


@dataclass
class _PerspectiveMaps:
    shape: tuple[int, int]
    output_shape: tuple[int, int]
    forward: np.ndarray
    inverse: np.ndarray
    map1: np.ndarray
    map2: np.ndarray


class _CurveKalman:
    """Small Kalman filter for x = a*y^2 + b*y + c in BEV coordinates."""

    def __init__(self) -> None:
        self.state: np.ndarray | None = None
        self.covariance: np.ndarray | None = None

    def update(self, measurement: np.ndarray, confidence: float) -> np.ndarray:
        measurement = measurement.astype(np.float64)
        if self.state is None or self.covariance is None:
            self.state = measurement
            self.covariance = np.eye(3, dtype=np.float64) * 4.0
            return self.state
        process_noise = np.diag([2e-7, 2e-4, 1.5])
        self.covariance = self.covariance + process_noise
        measurement_noise = np.diag([5e-6, 5e-3, 18.0]) / max(confidence, 0.15)
        gain = self.covariance @ np.linalg.inv(self.covariance + measurement_noise)
        self.state = self.state + gain @ (measurement - self.state)
        self.covariance = (np.eye(3) - gain) @ self.covariance
        return self.state

    def prediction(self) -> np.ndarray | None:
        return None if self.state is None else self.state.copy()

    def reset(self) -> None:
        self.state = None
        self.covariance = None


class IPMLaneDetector:
    """Bird's-eye lane extractor with global acquisition and local tracking."""

    def __init__(
        self,
        center_x_ratio: float = 0.5,
        source_top_y_ratio: float = 0.48,
        source_bottom_width_ratio: float = 0.90,
        source_top_width_ratio: float = 0.18,
        track_margin_px: int = 24,
        min_lane_pixels: int = 28,
        min_confidence: float = 0.35,
        processing_scale: float = 0.50,
        max_center_jump_ratio: float = 0.18,
        max_width_change_ratio: float = 0.45,
        max_tracking_misses: int = 3,
        camera_matrix: list[float] | None = None,
        distortion_coeffs: list[float] | None = None,
    ) -> None:
        self.center_x_ratio = center_x_ratio
        self.source_top_y_ratio = source_top_y_ratio
        self.source_bottom_width_ratio = source_bottom_width_ratio
        self.source_top_width_ratio = source_top_width_ratio
        self.track_margin_px = track_margin_px
        self.min_lane_pixels = min_lane_pixels
        self.min_confidence = min_confidence
        self.processing_scale = float(np.clip(processing_scale, 0.4, 1.0))
        self.max_center_jump_ratio = max_center_jump_ratio
        self.max_width_change_ratio = max_width_change_ratio
        self.max_tracking_misses = max(1, max_tracking_misses)
        self.camera_matrix = self._matrix(camera_matrix)
        self.distortion_coeffs = self._coefficients(distortion_coeffs)
        self._maps: _PerspectiveMaps | None = None
        self._undistort_shape: tuple[int, int] | None = None
        self._undistort_map1: np.ndarray | None = None
        self._undistort_map2: np.ndarray | None = None
        self._left_filter = _CurveKalman()
        self._right_filter = _CurveKalman()
        self._tracking_misses = 0
        self.last_reference_score = 1.0
        self.last_mode = "search"

    def detect(
        self,
        frame: np.ndarray,
        vehicle_bboxes: list[tuple[float, float, float, float]] | None = None,
        reference_polygon: np.ndarray | None = None,
    ) -> tuple[LaneInfo, float]:
        height, width = frame.shape[:2]
        corrected = self._undistort(self._remove_vehicles(frame, vehicle_bboxes))
        maps = self._ensure_maps(width, height)
        bev = cv2.remap(corrected, maps.map1, maps.map2, interpolation=cv2.INTER_LINEAR,
                        borderMode=cv2.BORDER_CONSTANT)
        mask = self._lane_mask(bev)
        reference_bev = self._reference_to_bev(reference_polygon, maps)
        left, right, mode = self._find_candidates(mask, reference_bev)
        if left is None or right is None:
            self._mark_missed()
            return LaneInfo(None, None, None, None), 0.0

        left_fit, left_quality = self._robust_fit(left[0], left[1])
        right_fit, right_quality = self._robust_fit(right[0], right[1])
        if left_fit is None or right_fit is None:
            self._mark_missed()
            return LaneInfo(None, None, None, None), 0.0

        confidence = min(left_quality, right_quality)
        raw_info = self._to_image_lane(left_fit, right_fit, maps, width, height)
        if raw_info is None:
            self._mark_missed()
            return LaneInfo(None, None, None, None), 0.0
        self.last_reference_score = self._reference_score(raw_info, reference_polygon, width)
        confidence *= 0.55 + 0.45 * self.last_reference_score
        if (confidence < self.min_confidence
                or self.last_reference_score < 0.18
                or not self._is_temporally_plausible(left_fit, right_fit, maps)):
            self._mark_missed()
            return LaneInfo(None, None, None, None), 0.0
        left_fit = self._left_filter.update(left_fit, confidence)
        right_fit = self._right_filter.update(right_fit, confidence)
        info = self._to_image_lane(left_fit, right_fit, maps, width, height)
        if info is None:
            self._mark_missed()
            return LaneInfo(None, None, None, None), 0.0
        self._tracking_misses = 0
        self.last_mode = mode
        return info, confidence

    def _mark_missed(self) -> None:
        self._tracking_misses += 1
        self.last_mode = "lost"
        if self._tracking_misses >= self.max_tracking_misses:
            # A stale model must not keep rejecting a newly entered curve forever.
            self._left_filter.reset()
            self._right_filter.reset()
            self._tracking_misses = 0
            self.last_mode = "search"

    @staticmethod
    def _remove_vehicles(
        frame: np.ndarray,
        vehicle_bboxes: list[tuple[float, float, float, float]] | None,
    ) -> np.ndarray:
        if not vehicle_bboxes:
            return frame
        masked = frame.copy()
        height, width = frame.shape[:2]
        for x1, y1, x2, y2 in vehicle_bboxes:
            pad_x = max(2, int((x2 - x1) * 0.12))
            pad_y = max(2, int((y2 - y1) * 0.10))
            cv2.rectangle(
                masked,
                (max(0, int(x1) - pad_x), max(0, int(y1) - pad_y)),
                (min(width - 1, int(x2) + pad_x), min(height - 1, int(y2) + pad_y)),
                (0, 0, 0),
                -1,
            )
        return masked

    @staticmethod
    def _matrix(values: list[float] | None) -> np.ndarray | None:
        if values is None or len(values) != 9:
            return None
        return np.asarray(values, dtype=np.float64).reshape(3, 3)

    @staticmethod
    def _coefficients(values: list[float] | None) -> np.ndarray | None:
        if values is None or len(values) < 4:
            return None
        return np.asarray(values, dtype=np.float64).reshape(-1, 1)

    def _undistort(self, frame: np.ndarray) -> np.ndarray:
        if self.camera_matrix is None or self.distortion_coeffs is None:
            return frame
        height, width = frame.shape[:2]
        if self._undistort_shape != (height, width):
            self._undistort_map1, self._undistort_map2 = cv2.initUndistortRectifyMap(
                self.camera_matrix, self.distortion_coeffs, None, self.camera_matrix,
                (width, height), cv2.CV_16SC2,
            )
            self._undistort_shape = (height, width)
        assert self._undistort_map1 is not None and self._undistort_map2 is not None
        return cv2.remap(frame, self._undistort_map1, self._undistort_map2, cv2.INTER_LINEAR)

    def _ensure_maps(self, width: int, height: int) -> _PerspectiveMaps:
        if self._maps is not None and self._maps.shape == (height, width):
            return self._maps
        out_height = max(32, int(round(height * self.processing_scale)))
        out_width = max(32, int(round(width * self.processing_scale)))
        top_y = float(np.clip(self.source_top_y_ratio, 0.15, 0.85) * height)
        bottom_half = self.source_bottom_width_ratio * width / 2
        top_half = self.source_top_width_ratio * width / 2
        center = self.center_x_ratio * width
        source = np.float32([
            [center - bottom_half, height - 1],
            [center - top_half, top_y],
            [center + top_half, top_y],
            [center + bottom_half, height - 1],
        ])
        # A narrow output border prevents interpolation artifacts at the edges.
        margin = out_width * 0.12
        destination = np.float32([
            [margin, out_height - 1], [margin, 0],
            [out_width - margin, 0], [out_width - margin, out_height - 1],
        ])
        forward = cv2.getPerspectiveTransform(source, destination)
        inverse = cv2.getPerspectiveTransform(destination, source)
        yy, xx = np.indices((out_height, out_width), dtype=np.float32)
        points = np.stack((xx.ravel(), yy.ravel()), axis=1).reshape(-1, 1, 2)
        source_points = cv2.perspectiveTransform(points, inverse).reshape(out_height, out_width, 2)
        map1, map2 = cv2.convertMaps(
            source_points[:, :, 0], source_points[:, :, 1], cv2.CV_16SC2,
        )
        self._maps = _PerspectiveMaps((height, width), (out_height, out_width), forward, inverse, map1, map2)
        return self._maps

    @staticmethod
    def _lane_mask(bev: np.ndarray) -> np.ndarray:
        hls = cv2.cvtColor(bev, cv2.COLOR_BGR2HLS)
        lightness = hls[:, :, 1]
        # Fast adaptive threshold: costly contrast enhancement is reserved for dark frames.
        if float(lightness.mean()) < 82.0:
            lightness = cv2.createCLAHE(clipLimit=1.8, tileGridSize=(8, 8)).apply(lightness)
        sobel = cv2.Sobel(lightness, cv2.CV_16S, 1, 0, ksize=3)
        gradient = cv2.convertScaleAbs(sobel)
        _, gradient = cv2.threshold(gradient, 32, 255, cv2.THRESH_BINARY)
        # A fixed white threshold misses faded markings on dark asphalt.  The
        # percentile adapts to illumination while the floor rejects road texture.
        white_floor = int(np.clip(np.percentile(hls[:, :, 1], 85), 70, 150))
        white = cv2.inRange(hls, (0, white_floor, 0), (180, 255, 160))
        yellow = cv2.inRange(hls, (12, 48, 40), (45, 255, 255))
        mask = cv2.bitwise_or(gradient, cv2.bitwise_or(white, yellow))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((max(3, min(11, bev.shape[0] // 10)), 3), np.uint8))
        return cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))

    def _is_temporally_plausible(
        self,
        left_fit: np.ndarray,
        right_fit: np.ndarray,
        maps: _PerspectiveMaps,
    ) -> bool:
        previous_left = self._left_filter.prediction()
        previous_right = self._right_filter.prediction()
        if previous_left is None or previous_right is None:
            return True
        y_bottom = maps.output_shape[0] - 1
        center = (np.polyval(left_fit, y_bottom) + np.polyval(right_fit, y_bottom)) / 2
        width = np.polyval(right_fit, y_bottom) - np.polyval(left_fit, y_bottom)
        previous_center = (np.polyval(previous_left, y_bottom) + np.polyval(previous_right, y_bottom)) / 2
        previous_width = np.polyval(previous_right, y_bottom) - np.polyval(previous_left, y_bottom)
        if previous_width <= 1:
            return False
        if abs(center - previous_center) > maps.output_shape[1] * self.max_center_jump_ratio:
            return False
        return abs(width - previous_width) <= previous_width * self.max_width_change_ratio

    def _find_candidates(
        self,
        mask: np.ndarray,
        reference_bev: np.ndarray | None,
    ) -> tuple[tuple[np.ndarray, np.ndarray] | None, tuple[np.ndarray, np.ndarray] | None, str]:
        ys, xs = mask.nonzero()
        if len(xs) < self.min_lane_pixels * 2:
            return None, None, "search"
        left_prediction = self._left_filter.prediction()
        right_prediction = self._right_filter.prediction()
        if left_prediction is not None and right_prediction is not None:
            left_center = np.polyval(left_prediction, ys)
            right_center = np.polyval(right_prediction, ys)
            left_mask = np.abs(xs - left_center) <= self.track_margin_px
            right_mask = np.abs(xs - right_center) <= self.track_margin_px
            if left_mask.sum() >= self.min_lane_pixels and right_mask.sum() >= self.min_lane_pixels:
                return (ys[left_mask], xs[left_mask]), (ys[right_mask], xs[right_mask]), "track"

        height, width = mask.shape
        histogram = mask[int(height * 0.55):].sum(axis=0)
        # Dashed markings may have no paint in the nearest band.
        if not np.any(histogram):
            histogram = mask.sum(axis=0)
        center = int(width * self.center_x_ratio)
        expected_left = expected_right = None
        if reference_bev is not None and len(reference_bev) >= 4:
            expected_left = float(reference_bev[0][0])
            expected_right = float(reference_bev[3][0])
            center = int(np.clip((expected_left + expected_right) / 2, width * 0.25, width * 0.75))
        left_base = self._weighted_peak(histogram, 0, center, expected_left)
        right_base = self._weighted_peak(histogram, center, width, expected_right)
        if histogram[left_base] == 0 or histogram[right_base] == 0:
            return None, None, "search"
        windows = 8
        window_height = max(1, height // windows)
        margin = max(self.track_margin_px, int(width * 0.06))
        min_recenter = 8
        left_indices: list[np.ndarray] = []
        right_indices: list[np.ndarray] = []
        left_x, right_x = left_base, right_base
        for window in range(windows):
            y_low = height - (window + 1) * window_height
            y_high = height - window * window_height
            in_y = (ys >= y_low) & (ys < y_high)
            left_window = np.flatnonzero(in_y & (np.abs(xs - left_x) <= margin))
            right_window = np.flatnonzero(in_y & (np.abs(xs - right_x) <= margin))
            left_indices.append(left_window)
            right_indices.append(right_window)
            if len(left_window) >= min_recenter:
                left_x = int(np.median(xs[left_window]))
            if len(right_window) >= min_recenter:
                right_x = int(np.median(xs[right_window]))
        left_idx = np.concatenate(left_indices) if left_indices else np.empty(0, dtype=int)
        right_idx = np.concatenate(right_indices) if right_indices else np.empty(0, dtype=int)
        if len(left_idx) < self.min_lane_pixels or len(right_idx) < self.min_lane_pixels:
            return None, None, "search"
        return (ys[left_idx], xs[left_idx]), (ys[right_idx], xs[right_idx]), "acquire"

    @staticmethod
    def _weighted_peak(
        histogram: np.ndarray,
        start: int,
        stop: int,
        expected: float | None,
    ) -> int:
        if stop <= start:
            return max(0, min(start, len(histogram) - 1))
        scores = histogram[start:stop].astype(np.float64)
        if expected is not None:
            xs = np.arange(start, stop, dtype=np.float64)
            sigma = max(8.0, len(histogram) * 0.14)
            scores *= 1.0 + 1.2 * np.exp(-0.5 * ((xs - expected) / sigma) ** 2)
        return start + int(np.argmax(scores))

    @staticmethod
    def _reference_to_bev(reference_polygon: np.ndarray | None, maps: _PerspectiveMaps) -> np.ndarray | None:
        if reference_polygon is None or len(reference_polygon) < 4:
            return None
        points = reference_polygon.astype(np.float32).reshape(-1, 1, 2)
        return cv2.perspectiveTransform(points, maps.forward).reshape(-1, 2)

    @staticmethod
    def _reference_score(info: LaneInfo, reference_polygon: np.ndarray | None, width: int) -> float:
        if reference_polygon is None or len(reference_polygon) < 4:
            return 1.0
        if info.left_lane is None or info.right_lane is None:
            return 0.0
        cand_left = float(info.left_lane[-1][0])
        cand_right = float(info.right_lane[-1][0])
        ref_left = float(reference_polygon[0][0])
        ref_right = float(reference_polygon[3][0])
        candidate_center = (cand_left + cand_right) / 2
        reference_center = (ref_left + ref_right) / 2
        reference_width = max(ref_right - ref_left, width * 0.10)
        candidate_width = max(cand_right - cand_left, 1.0)
        center_error = abs(candidate_center - reference_center) / reference_width
        width_error = abs(np.log(candidate_width / reference_width))
        center_score = np.exp(-0.5 * (center_error / 0.45) ** 2)
        width_score = np.exp(-0.5 * (width_error / 0.90) ** 2)
        return float(np.clip(center_score * width_score, 0.0, 1.0))

    def _robust_fit(self, ys: np.ndarray, xs: np.ndarray) -> tuple[np.ndarray | None, float]:
        if len(xs) < self.min_lane_pixels:
            return None, 0.0
        keep = np.ones(len(xs), dtype=bool)
        fit: np.ndarray | None = None
        for _ in range(3):
            if keep.sum() < self.min_lane_pixels:
                return None, 0.0
            fit = np.polyfit(ys[keep], xs[keep], 2)
            residual = np.abs(xs - np.polyval(fit, ys))
            median = float(np.median(residual[keep]))
            mad = float(np.median(np.abs(residual[keep] - median))) + 1e-3
            keep = residual <= max(5.0, median + 3.0 * mad)
        if fit is None:
            return None, 0.0
        residual = np.abs(xs[keep] - np.polyval(fit, ys[keep]))
        support = min(1.0, keep.sum() / 110.0)
        precision = float(np.exp(-float(np.mean(residual)) / 10.0)) if len(residual) else 0.0
        return fit, float(np.clip(support * precision, 0.0, 1.0))

    def _to_image_lane(
        self,
        left_fit: np.ndarray,
        right_fit: np.ndarray,
        maps: _PerspectiveMaps,
        width: int,
        height: int,
    ) -> LaneInfo | None:
        bev_height = maps.output_shape[0]
        y_top = int(bev_height * 0.12)
        y_bottom = bev_height - 1
        # Check the entire quadratic interval, not only sampled endpoints.
        gap = np.asarray(right_fit) - np.asarray(left_fit)
        probes = [float(y_top), float(y_bottom)]
        if abs(gap[0]) > 1e-12:
            vertex = -gap[1] / (2 * gap[0])
            if y_top < vertex < y_bottom:
                probes.append(float(vertex))
        if min(np.polyval(gap, probes)) <= 1.:
            return None
        points = np.float32([
            [[np.polyval(left_fit, y_top), y_top]],
            [[np.polyval(left_fit, y_bottom), y_bottom]],
            [[np.polyval(right_fit, y_top), y_top]],
            [[np.polyval(right_fit, y_bottom), y_bottom]],
        ])
        image_points = cv2.perspectiveTransform(points, maps.inverse).reshape(4, 2)
        image_points[:, 0] = np.clip(image_points[:, 0], 0, width - 1)
        image_points[:, 1] = np.clip(image_points[:, 1], 0, height - 1)
        left = image_points[:2].astype(np.int32)
        right = image_points[2:].astype(np.int32)
        if left[1, 0] >= right[1, 0] or left[0, 0] >= right[0, 0]:
            return None
        bottom_width = right[1, 0] - left[1, 0]
        top_width = right[0, 0] - left[0, 0]
        center = (left[1, 0] + right[1, 0]) / 2 / max(width, 1)
        # Reject geometries that cannot be the ego lane before they reach LDW.
        if not width * 0.18 <= bottom_width <= width * 0.86:
            return None
        if not width * 0.05 <= top_width <= bottom_width * 1.10:
            return None
        if not 0.20 <= center <= 0.80:
            return None
        if getattr(self, "curve_enabled", False):
            ys = np.linspace(y_top, y_bottom, 24)
            points = np.concatenate((np.column_stack((np.polyval(left_fit, ys), ys)),
                                     np.column_stack((np.polyval(right_fit, ys), ys)))).astype(np.float32)
            curved = cv2.perspectiveTransform(points.reshape(-1, 1, 2), maps.inverse).reshape(-1, 2)
            if not np.isfinite(curved).all():
                return None
            curved[:, 0] = np.clip(curved[:, 0], 0, width-1)
            curved[:, 1] = np.clip(curved[:, 1], 0, height-1)
            left, right = curved[:24].astype(np.int32), curved[24:].astype(np.int32)
            if np.any(left[:, 0] >= right[:, 0]):
                return None
            polygon = np.concatenate((left[::-1], right))
        else:
            polygon = np.array([left[1], left[0], right[0], right[1]], dtype=np.int32)
        vanishing = line_intersection(tuple(left[0]), tuple(left[-1]), tuple(right[0]), tuple(right[-1]))
        return LaneInfo(left, right, polygon, vanishing)
