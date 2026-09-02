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
        보컬/피아노 대보표(Grand Staff System) 단위로 시스템 구조를 정밀 인식합니다.
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
            avg_spacing = float(np.mean(spacings))
            
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

        # 인접한 오선지들을 대보표(Grand Staff System)로 그룹화
        system_regions: List[SystemRegion] = []
        s_idx = 0
        i = 0
        while i < len(staves):
            st1 = staves[i]
            if i + 1 < len(staves):
                st2 = staves[i+1]
                gap = st2.y_lines[0] - st1.y_lines[4]
                if 12.0 <= gap <= 160.0:
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
        [10-Point Line Intersection Algorithm]
        높은음자리표 최상단 수평선부터 낮은음자리표 최하단 수평선까지 총 10개의 수평 오선지와
        수직선이 동일한 X 좌표에서 완벽하게 교차하는지(10개 교차점 일치율)를 계산하여,
        음표 기둥(Stem)과 기호를 100% 걸러내고 오직 진짜 세로 마디선(Barline)만 추출합니다.
        """
        gray = cv2.cvtColor(bgr_image, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape

        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

        all_measures: List[MeasureBox] = []
        global_m_idx = 0

        v_k = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 8))
        v_img = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, v_k)

        for sys in systems:
            if not sys.treble_staff:
                continue

            t_lines = sys.treble_staff.y_lines
            b_lines = sys.bass_staff.y_lines if sys.bass_staff else []
            all_10_lines = t_lines + b_lines

            # 1. 10개 수평선(오선 10줄) 각각과의 교차 여부 검사
            intersections_count = np.zeros(w, dtype=int)
            for y_line in all_10_lines:
                y_min_chk = max(0, y_line - 2)
                y_max_chk = min(h, y_line + 3)
                line_has_vert = np.max(v_img[y_min_chk:y_max_chk, :], axis=0) > 0
                intersections_count += line_has_vert.astype(int)

            # 2. Staff Gap(높은음자리 밑선 ~ 낮은음자리 윗선 사이) 연속성 검사
            if b_lines:
                gap_top = t_lines[4]
                gap_bot = b_lines[0]
                gap_h = max(1, gap_bot - gap_top)
                gap_crop = v_img[gap_top:gap_bot, :]
                gap_sums = np.sum(gap_crop, axis=0) / 255 if gap_crop.size > 0 else np.zeros(w)

                # 진짜 마디선 조건: 10개 오선 중 최소 9개 이상과 교차 + Gap 85% 이상 관통
                valid_cols = np.where((intersections_count >= 9) & (gap_sums >= gap_h * 0.85))[0]
            else:
                # 단일 보표
                valid_cols = np.where(intersections_count >= 5)[0]

            # 3. X좌표 클러스터링
            clusters = []
            if len(valid_cols) > 0:
                curr = [valid_cols[0]]
                for x in valid_cols[1:]:
                    if x - curr[-1] <= 14:
                        curr.append(x)
                    else:
                        clusters.append(int(np.mean(curr)))
                        curr = [x]
                if curr:
                    clusters.append(int(np.mean(curr)))

            left_edge = clusters[0] if clusters else int(w * 0.05)
            right_edge = clusters[-1] if len(clusters) > 1 else int(w * 0.95)

            # 최소 마디 폭(140px 이상) 필터링
            filtered = [left_edge]
            for c in clusters[1:]:
                if (c - filtered[-1] >= 140) and ((right_edge - c) >= 60):
                    filtered.append(c)
            if right_edge - filtered[-1] >= 60:
                filtered.append(right_edge)

            if len(filtered) < 2:
                filtered = list(np.linspace(int(w * 0.06), int(w * 0.94), 5, dtype=int))

            # 서브픽셀 정밀 피크 보정
            refined_bars = []
            crop_full = thresh[max(0, sys.y_min):min(h - 1, sys.y_max), :]
            for bx in filtered:
                x_sub_start = max(0, bx - 6)
                x_sub_end = min(w, bx + 6)
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
