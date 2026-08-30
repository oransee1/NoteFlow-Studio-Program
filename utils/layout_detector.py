import cv2
import numpy as np
from dataclasses import dataclass, field
from typing import List, Tuple, Optional

@dataclass
class StaffInfo:
    staff_type: str  # "treble" 또는 "bass" 또는 "single"
    y_lines: List[int]  # 5개 오선지 Y 좌표 [line0(최상단), line1, line2, line3, line4(최하단)]
    line_spacing: float

@dataclass
class SystemRegion:
    system_index: int
    y_min: int
    y_max: int
    treble_staff: Optional[StaffInfo] = None
    bass_staff: Optional[StaffInfo] = None
    barline_xs: List[int] = field(default_factory=list)

@dataclass
class MeasureBox:
    measure_index: int
    system_index: int
    x1: int
    y1: int
    x2: int
    y2: int
    system_region: Optional[SystemRegion] = None

class SheetLayoutDetector:
    def __init__(self):
        pass

    def detect_staff_lines_and_systems(self, bgr_image: np.ndarray) -> List[SystemRegion]:
        """
        악보 이미지에서 5줄 오선지(Staff lines)의 정확한 픽셀 Y위치를 탐지하고,
        보컬/피아노 대권표(Grand Staff System) 단위로 시스템 구조를 정밀 인식합니다.
        """
        gray = cv2.cvtColor(bgr_image, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape

        # 이진화 (Otsu thresholding)
        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

        # 가로 수평선(오선지) 강조 모폴로지 필터
        horizontal_kernel_len = max(w // 12, 30)
        horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (horizontal_kernel_len, 1))
        detected_horizontal = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, horizontal_kernel, iterations=2)

        # Y축 피크(가로 프로젝션) 추출
        row_sums = np.sum(detected_horizontal, axis=1) / 255
        threshold_density = max(np.max(row_sums) * 0.20, horizontal_kernel_len * 0.3)
        line_y_indices = np.where(row_sums > threshold_density)[0]

        if len(line_y_indices) < 5:
            return [self._create_fallback_system(0, h, w)]

        # 연속 픽셀 클러스터링
        line_clusters = []
        curr = [line_y_indices[0]]
        for y in line_y_indices[1:]:
            if y - curr[-1] <= 4:
                curr.append(y)
            else:
                line_clusters.append(int(np.mean(curr)))
                curr = [y]
        if curr:
            line_clusters.append(int(np.mean(curr)))

        # 5개씩 묶어서 개별 오선지(Staff) 탐지
        staves: List[StaffInfo] = []
        idx = 0
        while idx <= len(line_clusters) - 5:
            group = line_clusters[idx:idx+5]
            spacings = [group[i+1] - group[i] for i in range(4)]
            avg_spacing = np.mean(spacings)
            
            if 4.0 <= avg_spacing <= 30.0 and max(spacings) - min(spacings) <= 10:
                staves.append(StaffInfo(
                    staff_type="single",
                    y_lines=group,
                    line_spacing=avg_spacing
                ))
                idx += 5
            else:
                idx += 1

        if not staves:
            return [self._create_fallback_system(0, h, w)]

        # 인접한 오선지들을 대권표(Grand Staff System)로 그룹화
        system_regions: List[SystemRegion] = []
        s_idx = 0
        i = 0
        while i < len(staves):
            st1 = staves[i]
            if i + 1 < len(staves):
                st2 = staves[i+1]
                gap = st2.y_lines[0] - st1.y_lines[4]
                if 12.0 <= gap <= 140.0:
                    st1.staff_type = "treble"
                    st2.staff_type = "bass"
                    sys_ymin = max(0, st1.y_lines[0] - 20)
                    sys_ymax = min(h - 1, st2.y_lines[4] + 20)
                    
                    sys_region = SystemRegion(
                        system_index=s_idx,
                        y_min=sys_ymin,
                        y_max=sys_ymax,
                        treble_staff=st1,
                        bass_staff=st2
                    )
                    system_regions.append(sys_region)
                    s_idx += 1
                    i += 2
                    continue

            st1.staff_type = "treble"
            sys_ymin = max(0, st1.y_lines[0] - 20)
            sys_ymax = min(h - 1, st1.y_lines[4] + 20)
            system_regions.append(SystemRegion(
                system_index=s_idx,
                y_min=sys_ymin,
                y_max=sys_ymax,
                treble_staff=st1,
                bass_staff=None
            ))
            s_idx += 1
            i += 1

        return system_regions

    def detect_barlines_and_measures(self, bgr_image: np.ndarray, systems: List[SystemRegion]) -> List[MeasureBox]:
        """
        오선지 세로 관통 마디 구분선(Barline)을 높은음자리/낮은음자리 오선지 높이에 맞추어 정밀 감지하고,
        마디 영역(MeasureBox)을 생성합니다.
        """
        gray = cv2.cvtColor(bgr_image, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape

        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

        all_measures: List[MeasureBox] = []
        global_m_idx = 0

        for sys in systems:
            if not sys.treble_staff:
                continue

            t_lines = sys.treble_staff.y_lines
            b_lines = sys.bass_staff.y_lines if sys.bass_staff else t_lines
            t_top, t_bot = t_lines[0], t_lines[4]
            b_top, b_bot = b_lines[0], b_lines[4]
            t_h = max(10, t_bot - t_top)
            b_h = max(10, b_bot - b_top)

            # 높은음자리 오선지 관통 세로선 탐지
            v_k_t = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(8, t_h - 4)))
            vt = cv2.morphologyEx(thresh[max(0, t_top - 2):min(h - 1, t_bot + 2), :], cv2.MORPH_OPEN, v_k_t)
            sums_t = np.sum(vt, axis=0) / 255

            # 낮은음자리 오선지 관통 세로선 탐지
            v_k_b = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(8, b_h - 4)))
            vb = cv2.morphologyEx(thresh[max(0, b_top - 2):min(h - 1, b_bot + 2), :], cv2.MORPH_OPEN, v_k_b)
            sums_b = np.sum(vb, axis=0) / 255

            # 대권표 결합 세로 마디선 점수 (양쪽 모두 관통하거나 최소 한쪽을 확실히 관통)
            score_v = (sums_t > (t_h - 6)).astype(int) * 2 + (sums_b > (b_h - 6)).astype(int) * 2
            cand_x = np.where(score_v >= 2)[0]

            clusters = []
            if len(cand_x) > 0:
                curr = [cand_x[0]]
                for x in cand_x[1:]:
                    if x - curr[-1] <= 15:
                        curr.append(x)
                    else:
                        clusters.append(int(np.mean(curr)))
                        curr = [x]
                if curr:
                    clusters.append(int(np.mean(curr)))

            left_edge = min(clusters) if clusters else int(w * 0.05)
            right_edge = max(clusters) if clusters else int(w * 0.95)

            # 최소 마디 폭(100px 이상) 간격으로 필터링
            filtered = [left_edge]
            for c in clusters:
                if (c - filtered[-1] >= 95) and ((right_edge - c) >= 50):
                    filtered.append(c)
            if right_edge - filtered[-1] >= 50:
                filtered.append(right_edge)

            # 만약 감지된 세로선이 2개 미만인 경우 시스템 균등 분할
            if len(filtered) < 2:
                filtered = list(np.linspace(int(w * 0.05), int(w * 0.95), 5, dtype=int))

            # 서브픽셀 정밀 피크 보정
            refined_bars = []
            crop_full = thresh[max(0, sys.y_min):min(h - 1, sys.y_max), :]
            for bx in filtered:
                x_sub_start = max(0, bx - 10)
                x_sub_end = min(w, bx + 10)
                sub_sums = np.sum(crop_full[:, x_sub_start:x_sub_end], axis=0)
                if len(sub_sums) > 0:
                    best_offset = int(np.argmax(sub_sums))
                    refined_bars.append(x_sub_start + best_offset)
                else:
                    refined_bars.append(bx)

            sys.barline_xs = refined_bars

            # 마디 영역 생성
            for i in range(len(refined_bars) - 1):
                mbox = MeasureBox(
                    measure_index=global_m_idx,
                    system_index=sys.system_index,
                    x1=refined_bars[i],
                    y1=sys.y_min,
                    x2=refined_bars[i+1],
                    y2=sys.y_max,
                    system_region=sys
                )
                all_measures.append(mbox)
                global_m_idx += 1

        return all_measures

    def _create_fallback_system(self, idx: int, h: int, w: int) -> SystemRegion:
        y_top = int(h * 0.15)
        y_bot = int(h * 0.25)
        lines = [y_top + i * 10 for i in range(5)]
        st = StaffInfo(staff_type="treble", y_lines=lines, line_spacing=10.0)
        return SystemRegion(
            system_index=idx,
            y_min=y_top - 20,
            y_max=y_bot + 20,
            treble_staff=st,
            bass_staff=None
        )
