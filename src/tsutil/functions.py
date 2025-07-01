import numpy as np
import cv2
from .common import *
#from PIL import Image
from typing import TextIO
import sys

# MARK: deshaking correction

class DeshakingCorrection:
    def __init__(self):
        self.base_image: np.ndarray|None = None
        self.sample_image: np.ndarray|None = None
        self.frame_index: int|None = None
        
        self.__gray_base_image = None
        self.__gray_sample_image = None
        self.__mat = np.eye(3, dtype=np.float32)

        self.estimated_matrix: np.ndarray|None = None
        self.estimated_angle: float|None = None
        self.estimated_dx: float|None = None
        self.estimated_dy: float|None = None

    def get_matrix(self):
        return self.__mat

    def set_base_image(self, base_image: np.ndarray):
        self.base_image = base_image
        self.__gray_base_image = cv2.cvtColor(base_image, cv2.COLOR_RGB2GRAY).astype(np.float32)

    def set_sample_image(self, sample_image: np.ndarray, frame_index: int=None):
        self.sample_image = sample_image
        self.__gray_sample_image = cv2.cvtColor(sample_image, cv2.COLOR_RGB2GRAY).astype(np.float32)
        self.frame_index = frame_index

    def compute(self, shaking_detection_fields: list[Rect], rotation_angle: float = 0.0, fd: TextIO=sys.stdout) -> np.ndarray:
        if self.base_image is None or self.sample_image is None:
            raise Exception('No base image or sample image.')
        frame_info = '' if self.frame_index is None else f'f{self.frame_index + 1:05d}: '
        h, w = self.base_image.shape[:2]
        mat_r = cv2.getRotationMatrix2D((w/2, h/2), rotation_angle, 1.0)
        mat_r =np.vstack([mat_r, (0, 0, 1)], dtype=np.float32)
        if not len(shaking_detection_fields):
            self.__mat = mat_r
            return self.__mat
        base_points = []
        sample_points = []
        for i, f in enumerate(shaking_detection_fields):
            hann = cv2.createHanningWindow(f.get_size(), cv2.CV_32F)
            delta, response = cv2.phaseCorrelate(
                normalize_array(self.__gray_base_image[f.top:f.bottom, f.left:f.right]), 
                normalize_array(self.__gray_sample_image[f.top:f.bottom, f.left:f.right]), 
                hann
            )
            print(f'{frame_info}A{i + 1}: {delta=} {response=}', file=fd)
            #Image.fromarray(self.base_image[f.top:f.bottom, f.left:f.right, :]).save('base.png')
            #Image.fromarray(self.sample_image[f.top:f.bottom, f.left:f.right, :]).save('sample.png')
            cx, cy = f.get_center()
            base_points.append([cx, cy])
            sample_points.append([cx + delta[0], cy + delta[1]])
        base_points = np.array(base_points, dtype=np.float32)
        sample_points = np.array(sample_points, dtype=np.float32)
        print(f'{frame_info}{base_points=}', file=fd)
        print(f'{frame_info}{sample_points=}', file=fd)
        mat, angle, offset = estimate_rigid_transform_homography(sample_points, base_points)
        self.estimated_matrix = mat
        self.estimated_angle = float(angle)
        self.estimated_dx = float(offset[0])
        self.estimated_dy = float(offset[1])
        print(f'{frame_info}estimated_angle={self.estimated_angle} estimated_dx={self.estimated_dx} estimated_dy={self.estimated_dy}', file=fd)
        self.__mat = mat_r @ self.estimated_matrix
        return self.__mat

# MARK: functions

def estimate_rigid_transform_homography(src1: np.ndarray, src2: np.ndarray) -> tuple[np.ndarray, np.float32, np.ndarray]:
    # 1. 重心で中心化
    centroid1 = np.mean(src1, axis=0)
    centroid2 = np.mean(src2, axis=0)
    centered1 = src1 - centroid1
    centered2 = src2 - centroid2
    
    # 2. 最小二乗誤差で回転行列を求める（SVD）
    #    Kabschアルゴリズム: https://en.wikipedia.org/wiki/Kabsch_algorithm
    H = centered1.T @ centered2
    U, S, Vt = np.linalg.svd(H)
    R = Vt.T @ U.T
    
    # 反転のチェック（反射対策）
    if np.linalg.det(R) < 0:
        Vt[1, :] *= -1
        R = Vt.T @ U.T
    
    # 3. 並進ベクトル
    t = centroid2 - R @ centroid1
    
    # 4. アフィン行列（2×3）→ ホモグラフィ行列（3×3）に拡張
    H_affine = np.eye(3, dtype=np.float32)
    H_affine[:2, :2] = R.astype(np.float32)
    H_affine[:2, 2] = t.astype(np.float32)
    
    # 5. 回転角の算出
    theta_deg = np.degrees(np.arctan2(R[1, 0], R[0, 0]))

    # 6. 戻り値は(回転+平行移動のアフィン変換行列(3x3), 回転角, 平行移動量
    return H_affine, theta_deg, H_affine[:2, 2]

def compute_rigid_transform_homography(angle: float, dx: float, dy: float):
    a = np.radians(angle)
    c = np.cos(a, dtype=np.float32)
    s = np.sin(a, dtype=np.float32)
    return np.array([
        [c, -s, dx], 
        [s, c, dy], 
        [0, 0, 1]
    ], dtype=np.float32)

def normalize_array(src: np.ndarray) -> np.ndarray:
    min = np.min(src)
    max = np.max(src)
    if min == max:
        return np.full_like(src, 0)
    return (src - min) / (max - min)

def unsharp_mask(img: np.ndarray, k: float=1.5):
    kernel = _make_sharp_kernel(k)
    return np.clip(cv2.filter2D(img, -1, kernel), 0, 255).astype(np.uint8)

def _make_sharp_kernel(k):
    return np.array([
        [-k / 9, -k / 9, -k / 9],
        [-k / 9, 1 + 8 * k / 9, -k / 9],
        [-k / 9, -k / 9, -k / 9]
    ], np.float32)

def sigmoid_space(start, stop, n, c1=-10, c2=10):
    sigmoid = 1 / (1 + np.exp(-np.linspace(c1, c2, n)))
    sigmoid = (sigmoid - sigmoid.min()) / (sigmoid.max() - sigmoid.min())
    return start + (stop - start) * sigmoid

def sin_space(start, stop, n):
    s = np.sin(np.linspace(-np.pi/2, np.pi/2, n))
    s = (s - s.min()) / (s.max() - s.min())
    return start + (stop - start) * s
