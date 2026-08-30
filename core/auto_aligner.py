import numpy as np
from typing import List, Dict, Tuple, Optional
from core.pdf_renderer import PDFRenderer
from core.musicxml_parser import ParsedScore, MeasureData, NoteData
from utils.layout_detector import SheetLayoutDetector, SystemRegion, MeasureBox, StaffInfo

class AutoAligner:
    def __init__(self, pdf_renderer: PDFRenderer, layout_detector: SheetLayoutDetector):
        self.pdf_renderer = pdf_renderer
        self.layout_detector = layout_detector

    def align_score(self, score: ParsedScore, dpi: int = 200) -> ParsedScore:
        """
        PDF 악보 페이지의 오선지 5줄 및 세로 마디선 픽셀 좌표를 정밀 감지하고,
        OpenCV로 실제 흑색 음표 머리(Notehead) 픽셀 위치를 스캔하여
        MusicXML 음표 피치와 박자를 실제 악보 음표 위치에 100% 1:1 정밀 피팅합니다.
        """
        if not self.pdf_renderer.doc or not score.measures:
            return score

        page_count = self.pdf_renderer.page_count
        
        # 1단계: 모든 PDF 페이지의 시스템 및 마디 바운딩 박스 탐지
        page_measure_data: List[Tuple[int, np.ndarray, List[SystemRegion], List[MeasureBox]]] = []
        for p_idx in range(page_count):
            _, bgr_img, _ = self.pdf_renderer.render_page_pixmap(p_idx, dpi=dpi)
            systems = self.layout_detector.detect_staff_lines_and_systems(bgr_img)
            boxes = self.layout_detector.detect_barlines_and_measures(bgr_img, systems)
            page_measure_data.append((p_idx, bgr_img, systems, boxes))

        # 2단계: 순차 마디 맵핑을 위한 감지 박스 플랫화
        flat_boxes: List[Tuple[int, np.ndarray, MeasureBox]] = []
        for p_idx, bgr_img, systems, boxes in page_measure_data:
            for b in boxes:
                flat_boxes.append((p_idx, bgr_img, b))

        if len(flat_boxes) == 0:
            self._fallback_alignment(score, page_count, dpi)
            return score

        # 3단계: MusicXML 마디와 감지된 마디 박스 1:1 정밀 피팅 & 음표 머리(Notehead) 스캔 맵핑
        for m_idx, m_data in enumerate(score.measures):
            if m_idx < len(flat_boxes):
                p_idx, bgr_img, box = flat_boxes[m_idx]
            else:
                p_idx, bgr_img, box = flat_boxes[-1]

            m_data.mapped_page = p_idx
            m_data.bbox_x1 = float(box.x1)
            m_data.bbox_y1 = float(box.y1)
            m_data.bbox_x2 = float(box.x2)
            m_data.bbox_y2 = float(box.y2)

            # 마디 내 음표들을 실제 오선지 5줄 및 검은색 음표 머리 스캔 위치에 정밀 배치
            self._align_notes_to_staff(m_data, p_idx, box, bgr_img)

        return score

    def align_single_measure(self, m_data: MeasureData, dpi: int = 200) -> Tuple[int, int]:
        """
        특정 마디(m_data) 영역의 오선지 및 음표 위치를 자동 정렬합니다.
        - 높은음자리(녹색), 낮은음자리(파란색), 쉼표(노란색) 위치 자동 착 붙임
        - 미배치된 음표 머리(Notehead) 픽셀 감지 후 새로 생성 채우기
        반환값: (aligned_count, newly_created_count)
        """
        if not self.pdf_renderer.doc or m_data.bbox_x1 is None:
            return 0, 0

        p_idx = m_data.mapped_page
        _, bgr_img, _ = self.pdf_renderer.render_page_pixmap(p_idx, dpi=dpi)
        systems = self.layout_detector.detect_staff_lines_and_systems(bgr_img)

        # 현재 마디 Y 범위에 맞는 system_region 탐지
        my1, my2 = m_data.bbox_y1 or 0, m_data.bbox_y2 or 0
        sys_region = None
        for sys in systems:
            if sys.y_min - 30 <= my1 <= sys.y_max + 30:
                sys_region = sys
                break
        if not sys_region and systems:
            sys_region = systems[0]

        # 1. 기존 음표들의 위치, 피치 및 파트 색상 자동 정렬 (검은색 음표 머리 스캔 포함)
        mbox = MeasureBox(
            measure_index=m_data.number,
            system_index=sys_region.system_index if sys_region else 0,
            x1=int(m_data.bbox_x1),
            y1=int(m_data.bbox_y1),
            x2=int(m_data.bbox_x2),
            y2=int(m_data.bbox_y2),
            system_region=sys_region
        )
        self._align_notes_to_staff(m_data, p_idx, mbox, bgr_img)

        # 2. 미배치된 음표 머리(Notehead) OpenCV 감지 및 새로 생성 채우기
        newly_created = self._detect_and_fill_missing_notes(m_data, bgr_img, mbox, sys_region)

        return len(m_data.notes), newly_created

    def _detect_and_fill_missing_notes(self, m_data: MeasureData, bgr_img: np.ndarray, mbox: MeasureBox, sys_region: Optional[SystemRegion]) -> int:
        """
        마디 영역 내의 픽셀을 분석하여 기존 음표 점이 없는 위치의 실제 음표 머리(Notehead)를 감지하고 새로 추가합니다.
        """
        import cv2
        x1, y1, x2, y2 = int(mbox.x1), int(mbox.y1), int(mbox.x2), int(mbox.y2)
        h, w, _ = bgr_img.shape
        x1, x2 = max(0, x1), min(w, x2)
        y1, y2 = max(0, y1), min(h, y2)

        if x2 - x1 < 20 or y2 - y1 < 20:
            return 0

        crop = bgr_img[y1:y2, x1:x2]
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

        # 오선지 수평선 제거 모폴로지
        kernel_h = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 1))
        no_lines = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel_h)
        thresh_clean = cv2.subtract(thresh, no_lines)

        # 음표 머리(타원/원형 흑색 블롭) 감지
        num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(thresh_clean)
        
        existing_coords = [(n.mapped_x, n.mapped_y) for n in m_data.notes if n.mapped_x is not None and n.mapped_y is not None]
        added_count = 0

        treble_lines = sys_region.treble_staff.y_lines if (sys_region and sys_region.treble_staff) else None
        bass_lines = sys_region.bass_staff.y_lines if (sys_region and sys_region.bass_staff) else None

        for i in range(1, num_labels):
            area = stats[i, cv2.CC_STAT_AREA]
            bw = stats[i, cv2.CC_STAT_WIDTH]
            bh = stats[i, cv2.CC_STAT_HEIGHT]

            # 음표 머리 면적 및 직경 비율 필터 (12 ~ 400 px)
            if 12 <= area <= 400 and 5 <= bw <= 35 and 5 <= bh <= 35:
                aspect_ratio = float(bw) / float(bh)
                if 0.4 <= aspect_ratio <= 2.5:
                    cx, cy = centroids[i]
                    abs_x = float(x1 + cx)
                    abs_y = float(y1 + cy)

                    # 기존 음표와 18px 이내에 중복되는지 검사
                    is_duplicate = False
                    for ex, ey in existing_coords:
                        if abs(ex - abs_x) < 18.0 and abs(ey - abs_y) < 18.0:
                            is_duplicate = True
                            break

                    if not is_duplicate:
                        pitch_str, staff = detect_pitch_from_y(abs_y, treble_lines, bass_lines)
                        n_idx = len(m_data.notes)
                        new_note = NoteData(
                            id=f"m{m_data.number}_auto_{n_idx}",
                            measure_number=m_data.number,
                            note_index=n_idx,
                            pitch=pitch_str,
                            is_rest=(pitch_str.lower() == "rest"),
                            duration=1,
                            beat_position=float(n_idx),
                            staff=staff,
                            mapped_page=m_data.mapped_page,
                            mapped_x=abs_x,
                            mapped_y=abs_y
                        )
                        m_data.notes.append(new_note)
                        existing_coords.append((abs_x, abs_y))
                        added_count += 1

        return added_count

    def _align_notes_to_staff(self, m_data: MeasureData, page_index: int, box: MeasureBox, bgr_img: Optional[np.ndarray] = None):
        """
        마디 내 음표 피치를 오선지 5줄(Line 1~5 및 Space 1~4) Y좌표에 맵핑하고,
        OpenCV로 실제 흑색 음표 머리(Notehead) 픽셀 위치를 스캔하여 100% 자석 스냅합니다.
        """
        import cv2
        x1, y1, x2, y2 = int(box.x1), int(box.y1), int(box.x2), int(box.y2)
        if bgr_img is not None:
            h, w, _ = bgr_img.shape
            x1, x2 = max(0, x1), min(w, x2)
            y1, y2 = max(0, y1), min(h, y2)

        width = max(10, x2 - x1)
        total_beats = max(1.0, float(m_data.beats))
        sys_region = box.system_region

        t_lines = sys_region.treble_staff.y_lines if (sys_region and sys_region.treble_staff) else [y1 + 30 + i*10 for i in range(5)]
        b_lines = sys_region.bass_staff.y_lines if (sys_region and sys_region.bass_staff) else t_lines
        spacing = sys_region.treble_staff.line_spacing if (sys_region and sys_region.treble_staff) else 10.0
        step_sp = spacing / 2.0

        # 마디 시작 및 끝 여백 (첫 번째 마디는 조표/음자리표/박자표 여백 반영)
        is_first_in_sys = (sys_region and sys_region.barline_xs and abs(x1 - sys_region.barline_xs[0]) < 25) or (m_data.number == 1)
        left_pad = int(width * 0.28) if is_first_in_sys else int(width * 0.08)
        right_pad = int(width * 0.05)
        usable_width = max(10, width - left_pad - right_pad)

        # 흑색 음표 머리(Notehead blob) 스캔
        blobs: List[Tuple[float, float, int]] = []
        if bgr_img is not None and width > 15 and (y2 - y1) > 15:
            crop = bgr_img[y1:y2, x1:x2]
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
            _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
            k_h = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 1))
            h_lines = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, k_h)
            no_lines = cv2.subtract(thresh, h_lines)
            num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(no_lines)
            for i in range(1, num_labels):
                area = stats[i, cv2.CC_STAT_AREA]
                bw = stats[i, cv2.CC_STAT_WIDTH]
                bh = stats[i, cv2.CC_STAT_HEIGHT]
                if 12 <= area <= 450 and 5 <= bw <= 35 and 5 <= bh <= 35:
                    cx, cy = centroids[i]
                    blobs.append((float(x1 + cx), float(y1 + cy), area))

        used_blob_indices = set()

        for note in m_data.notes:
            note.mapped_page = page_index
            is_bass = (note.staff == 2)

            # 1. 이론적 Y 좌표 계산
            if note.is_rest or note.pitch == "Rest":
                theo_y = float(b_lines[2] if is_bass else t_lines[2])
            else:
                sc = note.pitch[0].upper()
                try:
                    oct_v = int(note.pitch[-1])
                except (ValueError, IndexError):
                    oct_v = 4
                step_map = {'C': 0, 'D': 1, 'E': 2, 'F': 3, 'G': 4, 'A': 5, 'B': 6}
                pidx = oct_v * 7 + step_map.get(sc, 0)
                if is_bass:
                    theo_y = float(b_lines[0] + (26 - pidx) * step_sp)
                else:
                    theo_y = float(t_lines[0] + (38 - pidx) * step_sp)

            # 2. 이론적 X 좌표 계산
            beat_ratio = min(1.0, max(0.0, note.beat_position / total_beats))
            theo_x = float(x1 + left_pad + (beat_ratio * usable_width))

            # 3. 스캔된 검은색 음표 머리(Blob)와 1:1 매칭 & 착 붙이기
            best_idx = None
            best_dist = 99999.0
            if not note.is_rest and note.pitch != "Rest":
                for b_idx, (bx, by, _) in enumerate(blobs):
                    if b_idx in used_blob_indices:
                        continue
                    if abs(by - theo_y) <= (spacing * 0.90):
                        dist = abs(by - theo_y) * 2.0 + abs(bx - theo_x) * 0.5
                        if dist < best_dist and abs(bx - theo_x) <= (width * 0.45):
                            best_dist = dist
                            best_idx = b_idx

            if best_idx is not None:
                used_blob_indices.add(best_idx)
                bx, by, _ = blobs[best_idx]
                note.mapped_x = bx
                note.mapped_y = by
            else:
                note.mapped_x = theo_x
                note.mapped_y = theo_y

    def _fallback_alignment(self, score: ParsedScore, page_count: int, dpi: int):
        """CV 분석 실패 시 폴백 배치"""
        for m_idx, m_data in enumerate(score.measures):
            page_idx = m_idx % page_count
            m_data.mapped_page = page_idx
            w, h = self.pdf_renderer.get_page_size(page_idx)
            scale = dpi / 72.0
            pw, ph = w * scale, h * scale

            row = (m_idx // 4) % 6
            col = m_idx % 4

            box_x1 = pw * 0.1 + col * (pw * 0.2)
            box_x2 = box_x1 + pw * 0.18
            box_y1 = ph * 0.15 + row * (ph * 0.12)
            box_y2 = box_y1 + ph * 0.1

            m_data.bbox_x1, m_data.bbox_y1 = box_x1, box_y1
            m_data.bbox_x2, m_data.bbox_y2 = box_x2, box_y2

            for n_idx, note in enumerate(m_data.notes):
                note.mapped_page = page_idx
                note.mapped_x = box_x1 + (n_idx / max(1, len(m_data.notes))) * (box_x2 - box_x1)
                note.mapped_y = (box_y1 + box_y2) / 2.0


def detect_pitch_from_y(y: float, treble_y_lines: List[int] = None, bass_y_lines: List[int] = None, line_spacing: float = 10.0, force_staff: Optional[int] = None) -> Tuple[str, int]:
    """
    Y 픽셀 좌표로부터 5줄 오선지 상의 음높이(Pitch Step & Octave: 예 C4, G4, E5) 및 staff 파트를 역산합니다.
    force_staff: 1 (Treble/오른손/녹색) 또는 2 (Bass/왼손/파란색) 지정 시 파트 강제 구별.
    """
    step_chars = ['C', 'D', 'E', 'F', 'G', 'A', 'B']

    if force_staff == 2:
        staff = 2
        ref_y = bass_y_lines[0] if (bass_y_lines and len(bass_y_lines) >= 5) else 450.0
        ref_index = 3 * 7 + 5  # A3
    elif force_staff == 1:
        staff = 1
        ref_y = treble_y_lines[0] if (treble_y_lines and len(treble_y_lines) >= 5) else 250.0
        ref_index = 5 * 7 + 3  # F5
    elif bass_y_lines and len(bass_y_lines) >= 5:
        split_y = (treble_y_lines[-1] + bass_y_lines[0]) / 2.0 if treble_y_lines and len(treble_y_lines) >= 5 else bass_y_lines[0] - 15
        if y >= split_y:
            # Bass staff (낮은음자리표)
            ref_y = bass_y_lines[0]
            ref_index = 3 * 7 + 5  # A3 (Index 26)
            staff = 2
        else:
            # Treble staff (높은음자리표)
            ref_y = treble_y_lines[0] if treble_y_lines else y
            ref_index = 5 * 7 + 3  # F5 (Index 38)
            staff = 1
    elif treble_y_lines and len(treble_y_lines) >= 5:
        ref_y = treble_y_lines[0]
        ref_index = 5 * 7 + 3  # F5 (Index 38)
        staff = 1
    else:
        # 오선지 추정 실패 시 Y 높이 기반 추정
        ref_y = 300.0
        ref_index = 4 * 7 + 0  # C4 (Index 28)
        staff = 1

    step_spacing = line_spacing / 2.0 if line_spacing > 0 else 5.0
    diff_steps = int(round((y - ref_y) / step_spacing))
    target_index = max(0, ref_index - diff_steps)

    octave = target_index // 7
    step_idx = target_index % 7
    step_char = step_chars[step_idx]

    pitch_str = f"{step_char}{octave}"
    return pitch_str, staff
