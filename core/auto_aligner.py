import math
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
        PDF 악보 모든 페이지의 전체 대보표(모든 시스템 줄) 및 세로 마디선 픽셀 좌표를 정밀 감지하고,
        전체 대보표의 모든 세로 마디 영역에 100% 빠짐없이 세로 마디 박스(MeasureBox)를 1:1 완벽 생성 및 정밀 피팅합니다.
        OpenCV로 실제 흑색 음표 머리(Notehead) 픽셀 위치를 스캔하여 오선지에 정밀 배치합니다.
        """
        if not self.pdf_renderer.doc or not score.measures:
            return score

        page_count = self.pdf_renderer.page_count

        # 1단계: 모든 PDF 페이지의 시스템 및 마디 바운딩 박스 정밀 탐지
        all_detected_boxes: List[Tuple[int, np.ndarray, MeasureBox]] = []
        for p_idx in range(page_count):
            _, bgr_img, _ = self.pdf_renderer.render_page_pixmap(p_idx, dpi=dpi)
            systems = self.layout_detector.detect_staff_lines_and_systems(bgr_img)
            boxes = self.layout_detector.detect_barlines_and_measures(bgr_img, systems)
            
            # 만약 감지된 박스가 부족하거나 없는 경우 시스템별 기본 4분할 마디 생성 보장
            if not boxes and bgr_img is not None:
                h, w, _ = bgr_img.shape
                for s_i, sys_obj in enumerate(systems):
                    m_per_sys = 4
                    box_w = (w * 0.88) / float(m_per_sys)
                    for c in range(m_per_sys):
                        bx1 = int(w * 0.06 + c * box_w)
                        bx2 = int(bx1 + box_w - 4)
                        by1 = int(sys_obj.y_min)
                        by2 = int(sys_obj.y_max)
                        mbox = MeasureBox(
                            measure_index=len(all_detected_boxes),
                            system_index=sys_obj.system_index,
                            x1=bx1, y1=by1, x2=bx2, y2=by2,
                            system_region=sys_obj
                        )
                        boxes.append(mbox)

            for b in boxes:
                all_detected_boxes.append((p_idx, bgr_img, b))

        if not all_detected_boxes:
            self._fallback_alignment(score, page_count, dpi)
            return score

        total_detected = len(all_detected_boxes)

        # 2단계: 전체 대보표의 모든 세로 마디 영역이 빠짐없이 생성되도록 마디 확장 및 1:1 매핑
        import xml.etree.ElementTree as ET

        # 악보의 감지된 마디 박스 수가 기존 MusicXML 마디 수보다 많은 경우 새 마디 자동 확장
        while len(score.measures) < total_detected:
            new_num = len(score.measures) + 1
            new_m = MeasureData(
                number=new_num,
                time_signature=score.measures[-1].time_signature if score.measures else "4/4",
                beats=score.measures[-1].beats if score.measures else 4,
                beat_type=score.measures[-1].beat_type if score.measures else 4,
                divisions=score.measures[-1].divisions if score.measures else 1,
                fifths=score.measures[-1].fifths if score.measures else 0,
                notes=[]
            )
            score.measures.append(new_m)

            # XML DOM 트리에도 새 measure 엘리먼트 추가
            if score.root_element is not None:
                for part in score.root_element.findall("part"):
                    new_elem = ET.SubElement(part, "measure")
                    new_elem.set("number", str(new_num))

        score.total_measures = len(score.measures)

        # 3단계: 모든 대보표의 세로 마디 영역에 1:1 정밀 좌표 피팅 & 음표/쉼표 자동 감지 맵핑
        for m_idx, m_data in enumerate(score.measures):
            if m_idx < total_detected:
                p_idx, bgr_img, box = all_detected_boxes[m_idx]
            else:
                p_idx, bgr_img, box = all_detected_boxes[-1]

            m_data.mapped_page = p_idx
            m_data.bbox_x1 = float(box.x1)
            m_data.bbox_y1 = float(box.y1)
            m_data.bbox_x2 = float(box.x2)
            m_data.bbox_y2 = float(box.y2)

            # 기존 음표가 이미 존재하는 경우: 오선지에 1:1 정밀 정렬 수행
            if m_data.notes:
                self._align_notes_to_staff(m_data, p_idx, box, bgr_img)
            else:
                # 음표가 0개인 완전 빈 마디(4페이지 후반, 5페이지 등)에 대해서만 전수 스캔 및 생성
                self._detect_and_fill_missing_notes(m_data, bgr_img, box, box.system_region)

            # 동일 위치 2중 중복 음표 점 100% 제거 및 정제
            self.deduplicate_notes_in_measure(m_data)

        return score

    def deduplicate_notes_in_measure(self, m_data: MeasureData):
        """
        마디 내에 동일한 좌표 또는 15px 이내에 중복으로 겹쳐서 생성된 2중 음표/쉼표 점을 100% 정제하여
        단 1개의 고유한 음표 점만 유지합니다.
        """
        if not m_data or not m_data.notes:
            return

        unique_notes: List[NoteData] = []
        for note in m_data.notes:
            nx = note.mapped_x if note.mapped_x is not None else 0.0
            ny = note.mapped_y if note.mapped_y is not None else 0.0

            is_duplicate = False
            for idx, u_note in enumerate(unique_notes):
                ux = u_note.mapped_x if u_note.mapped_x is not None else 0.0
                uy = u_note.mapped_y if u_note.mapped_y is not None else 0.0

                dist = math.hypot(nx - ux, ny - uy)
                # 14px 이내 동일 위치에 존재하는 경우 중복으로 판정
                if dist <= 14.0 or (abs(nx - ux) <= 8.0 and note.staff == u_note.staff and note.pitch == u_note.pitch):
                    is_duplicate = True
                    # 만약 기존에 쉼표(Rest)가 들어가 있고 새 음표가 실제 Note이면 Note로 교체
                    if u_note.is_rest and not note.is_rest:
                        unique_notes[idx] = note
                    break

            if not is_duplicate:
                unique_notes.append(note)

        # 인덱스 재정렬
        for i, n in enumerate(unique_notes):
            n.note_index = i
        m_data.notes = unique_notes

    def align_single_measure(self, m_data: MeasureData, dpi: int = 200) -> Tuple[int, int]:
        """
        특정 마디(m_data) 영역의 오선지 및 음표 위치를 자동 정렬합니다.
        - 높은음자리(연두색), 낮은음자리(파란색), 쉼표(노란색) 위치 자동 착 붙임
        - 미배치된 음표 머리(Notehead) 및 쉼표 픽셀 감지 후 새로 생성 채우기
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
        if m_data.notes:
            self._align_notes_to_staff(m_data, p_idx, mbox, bgr_img)
        else:
            self._detect_and_fill_missing_notes(m_data, bgr_img, mbox, sys_region)

        self.deduplicate_notes_in_measure(m_data)
        return len(m_data.notes), 0

    def _detect_and_fill_missing_notes(self, m_data: MeasureData, bgr_img: Optional[np.ndarray], mbox: MeasureBox, sys_region: Optional[SystemRegion]) -> int:
        """
        마디 영역 내의 악보 픽셀을 정밀 분석하여:
        1. 높은음자리표 오선지 영역의 검은색 음표 머리를 스캔 -> 오름음자리표 음표(연두색 / staff=1 / C,D,E,F,G,A,B + Octave)
        2. 낮은음자리표 오선지 영역의 검은색 음표 머리를 스캔 -> 내림음자리표 음표(파란색 / staff=2 / C,D,E,F,G,A,B + Octave)
        3. 쉼표 기호(Rest)를 스캔 -> 쉼표(노란색 / is_rest=True / pitch="Rest")
        를 감지하고 중복 없이 추가합니다.
        """
        if bgr_img is None or sys_region is None:
            return 0

        import cv2
        x1, y1, x2, y2 = int(mbox.x1), int(mbox.y1), int(mbox.x2), int(mbox.y2)
        h, w, _ = bgr_img.shape
        x1, x2 = max(0, x1), min(w, x2)
        y1, y2 = max(0, y1), min(h, y2)

        if x2 - x1 < 15 or y2 - y1 < 15:
            return 0

        crop = bgr_img[y1:y2, x1:x2]
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

        # 오선지 수평선 제거 모폴로지
        kernel_h = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 1))
        h_lines = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel_h)
        no_lines = cv2.subtract(thresh, h_lines)

        # 연결 요소(블롭) 라벨링
        num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(no_lines)
        
        existing_coords = [(n.mapped_x, n.mapped_y) for n in m_data.notes if n.mapped_x is not None and n.mapped_y is not None]
        newly_detected: List[Tuple[float, float, str, int, bool]] = []  # (x, y, pitch, staff, is_rest)

        treble_lines = sys_region.treble_staff.y_lines if (sys_region and sys_region.treble_staff) else None
        bass_lines = sys_region.bass_staff.y_lines if (sys_region and sys_region.bass_staff) else None
        spacing = sys_region.treble_staff.line_spacing if (sys_region and sys_region.treble_staff) else 10.0

        split_y = (treble_lines[4] + bass_lines[0]) / 2.0 if (treble_lines and bass_lines) else (y1 + y2) / 2.0

        for i in range(1, num_labels):
            area = stats[i, cv2.CC_STAT_AREA]
            bw = stats[i, cv2.CC_STAT_WIDTH]
            bh = stats[i, cv2.CC_STAT_HEIGHT]

            # 마디 좌우 마디선과 직접 맞닿은 블롭은 마디선 잔여물이므로 제외
            cx, cy = centroids[i]
            if cx <= 3 or cx >= (x2 - x1 - 3):
                continue

            abs_x = float(x1 + cx)
            abs_y = float(y1 + cy)

            # 오선지 상하 범위를 크게 벗어난 블롭(가사, 마디번호 등) 필터링
            if treble_lines and abs_y < treble_lines[0] - spacing * 4:
                continue
            if bass_lines and abs_y > bass_lines[4] + spacing * 4:
                continue

            # 1. 쉼표(Rest) vs 음표(Note) 배타적 판별
            is_rest_blob = False
            is_note_blob = False

            # 4분 쉼표 (지그재그 세로 형태: 높이 15~36px, 너비 6~18px, 종횡비 0.3~0.75)
            if 15 <= bh <= 40 and 5 <= bw <= 20 and 0.25 <= float(bw) / float(bh) <= 0.75 and 40 <= area <= 350:
                t_mid = treble_lines[2] if treble_lines else 0
                b_mid = bass_lines[2] if bass_lines else 0
                if abs(abs_y - t_mid) <= spacing * 1.8 or abs(abs_y - b_mid) <= spacing * 1.8:
                    is_rest_blob = True
            # 2분/온 쉼표 (직사각형 블록: 가로로 길고 높이 4~12px, 면적 25~180)
            elif 4 <= bh <= 12 and 8 <= bw <= 25 and float(bw) / float(bh) >= 1.4 and 25 <= area <= 180:
                t_l3 = treble_lines[2] if treble_lines else 0
                b_l3 = bass_lines[2] if bass_lines else 0
                if abs(abs_y - t_l3) <= spacing * 1.2 or abs(abs_y - b_l3) <= spacing * 1.2:
                    is_rest_blob = True
            else:
                # 음표 머리(Notehead: 원형/타원형 검은색 머리) 판별
                aspect_ratio = float(bw) / float(max(1, bh))
                if (12 <= area <= 420 and 5 <= bw <= 36 and 5 <= bh <= 36 and 0.40 <= aspect_ratio <= 2.4):
                    is_note_blob = True

            if is_rest_blob or is_note_blob:
                # 18px 이내 중복 검사 (단 하나의 점만 생성)
                is_duplicate = False
                for ex, ey in existing_coords:
                    if math.hypot(ex - abs_x, ey - abs_y) <= 18.0:
                        is_duplicate = True
                        break

                if not is_duplicate:
                    if is_rest_blob:
                        staff = 1 if abs_y < split_y else 2
                        pitch_str = "Rest"
                        is_rest_val = True
                        final_y = abs_y
                    else:
                        snapped_y, pitch_str, staff, _ = snap_notehead_to_local_staff_line(
                            abs_x, abs_y, thresh, sys_region
                        )
                        final_y = snapped_y
                        is_rest_val = False

                    newly_detected.append((abs_x, final_y, pitch_str, staff, is_rest_val))
                    existing_coords.append((abs_x, final_y))

        # 가로 X좌표(시간순) 순서대로 정렬
        newly_detected.sort(key=lambda item: item[0])
        total_beats = max(1.0, float(getattr(m_data, 'beats', 4) or 4))
        usable_w = max(10.0, float(x2 - x1) * 0.85)
        pad_x = float(x1) + float(x2 - x1) * 0.08

        added_count = 0
        for abs_x, abs_y, pitch_str, staff, is_rest_val in newly_detected:
            n_idx = len(m_data.notes)
            rel_ratio = max(0.0, min(1.0, (abs_x - pad_x) / usable_w))
            beat_pos = round(rel_ratio * total_beats, 2)

            new_note = NoteData(
                id=f"m{m_data.number}_auto_{n_idx}",
                measure_number=m_data.number,
                note_index=n_idx,
                pitch=pitch_str,
                is_rest=is_rest_val,
                duration=1,
                beat_position=beat_pos,
                staff=staff,
                mapped_page=m_data.mapped_page,
                mapped_x=abs_x,
                mapped_y=abs_y
            )
            m_data.notes.append(new_note)
            added_count += 1

        # 음표가 아예 전혀 감지되지 않은 완전 빈 마디의 경우 기본 온쉼표 1개 자동 배치
        if not m_data.notes:
            t_mid_y = float(treble_lines[2]) if treble_lines else (y1 + (y2 - y1) * 0.35)
            mid_x = (x1 + x2) / 2.0
            default_rest = NoteData(
                id=f"m{m_data.number}_rest_0",
                measure_number=m_data.number,
                note_index=0,
                pitch="Rest",
                is_rest=True,
                duration=int(total_beats),
                beat_position=0.0,
                staff=1,
                mapped_page=m_data.mapped_page,
                mapped_x=mid_x,
                mapped_y=t_mid_y
            )
            m_data.notes.append(default_rest)
            added_count += 1

        self.deduplicate_notes_in_measure(m_data)
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
        no_lines = None
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
                snapped_y, pitch_str, staff, _ = snap_notehead_to_local_staff_line(bx, by, thresh, sys_region)
                note.mapped_x = bx
                note.mapped_y = snapped_y
                note.pitch = pitch_str
                note.staff = staff
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


def snap_notehead_to_local_staff_line(
    abs_x: float,
    abs_y: float,
    h_lines_img: Optional[np.ndarray] = None,
    sys_region: Optional[SystemRegion] = None,
    custom_treble_lines: Optional[List[int]] = None,
    custom_bass_lines: Optional[List[int]] = None,
    custom_spacing: Optional[float] = None
) -> Tuple[float, str, int, bool]:
    """
    음표 머리의 좌우 수평선(오선지 5줄 및 덧줄) 일부를 국소 스캔하여:
    1. 선을 관통하는 음표(On-Line): 해당 오선지/덧줄 중심선(Centerline)으로 서브픽셀 100% 자석 스냅 및 음계 계산
    2. 선 사이 칸에 위치한 음표(In-Space): 상하 두 선의 정중앙으로 서브픽셀 100% 자석 스냅 및 음계 계산
    반환값: (snapped_y, pitch_str, staff, is_line)
    """
    if custom_treble_lines and len(custom_treble_lines) >= 5:
        t_lines = custom_treble_lines
    elif sys_region and sys_region.treble_staff:
        t_lines = sys_region.treble_staff.y_lines
    else:
        t_lines = [int(abs_y - 50 + i * 10) for i in range(5)]

    if custom_bass_lines and len(custom_bass_lines) >= 5:
        b_lines = custom_bass_lines
    elif sys_region and sys_region.bass_staff:
        b_lines = sys_region.bass_staff.y_lines
    else:
        b_lines = [int(t_lines[4] + 50 + i * 10) for i in range(5)]

    if custom_spacing and custom_spacing > 0:
        spacing = custom_spacing
    elif sys_region and sys_region.treble_staff:
        spacing = sys_region.treble_staff.line_spacing
    elif len(t_lines) >= 2:
        spacing = float(t_lines[1] - t_lines[0])
    else:
        spacing = 10.0

    half_sp = spacing / 2.0

    split_y = (t_lines[4] + b_lines[0]) / 2.0 if (t_lines and b_lines) else float(t_lines[4] + 20)
    is_treble = (abs_y < split_y)
    ref_lines = t_lines if is_treble else b_lines
    staff = 1 if is_treble else 2

    # 1. 오선지 5개 줄 및 상하 덧줄(+-3줄) 후보 Y좌표 목록 생성
    candidate_lines = []
    for l_idx in range(-3, 8):
        ly = float(ref_lines[0] + l_idx * spacing)
        candidate_lines.append((l_idx, ly))

    # 가장 가까운 선 및 거리 계산
    closest_l_idx, closest_ly = min(candidate_lines, key=lambda item: abs(item[1] - abs_y))
    dist_to_line = abs(closest_ly - abs_y)

    # 2. 음표 좌우 영역 [abs_x-24 : abs_x-6] 및 [abs_x+6 : abs_x+24]의 수평선 연속성 스캔
    has_left_line = False
    has_right_line = False
    if h_lines_img is not None:
        h, w = h_lines_img.shape
        x_l1, x_l2 = max(0, int(abs_x - 24)), max(0, int(abs_x - 5))
        x_r1, x_r2 = min(w, int(abs_x + 5)), min(w, int(abs_x + 24))
        check_y = int(round(closest_ly))
        y_min_chk, y_max_chk = max(0, check_y - 2), min(h, check_y + 3)

        if y_max_chk > y_min_chk:
            if x_l2 > x_l1:
                has_left_line = bool(np.sum(h_lines_img[y_min_chk:y_max_chk, x_l1:x_l2]) > 0)
            if x_r2 > x_r1:
                has_right_line = bool(np.sum(h_lines_img[y_min_chk:y_max_chk, x_r1:x_r2]) > 0)

    # 3. 선(Line) vs 칸(Space) 결정
    # 줄과의 거리가 0.35 spacing 이내이면서 좌우에 수평선이 존재하거나 중심에 아주 가까운 경우 -> 선(Line)
    is_on_line = False
    if dist_to_line <= spacing * 0.35 and (has_left_line or has_right_line or dist_to_line <= spacing * 0.22):
        is_on_line = True
    elif h_lines_img is None and dist_to_line <= spacing * 0.28:
        is_on_line = True

    if is_on_line:
        # 선(Line) 음표: 정확한 선 중심선으로 100% 자석 스냅
        snapped_y = float(closest_ly)
        if is_treble:
            # -2=C6, -1=A5, 0=F5 (Line 5), 1=D5 (Line 4), 2=B4 (Line 3), 3=G4 (Line 2), 4=E4 (Line 1), 5=C4 (가온 덧줄), 6=A3
            treble_line_pitches = { -2: 'C6', -1: 'A5', 0: 'F5', 1: 'D5', 2: 'B4', 3: 'G4', 4: 'E4', 5: 'C4', 6: 'A3', 7: 'F3' }
            pitch_str = treble_line_pitches.get(closest_l_idx, "C4")
        else:
            # -1=C4 (가온 덧줄), 0=A3 (Line 5), 1=F3 (Line 4), 2=D3 (Line 3), 3=B2 (Line 2), 4=G2 (Line 1), 5=E2 (덧줄 1)
            bass_line_pitches = { -2: 'E4', -1: 'C4', 0: 'A3', 1: 'F3', 2: 'D3', 3: 'B2', 4: 'G2', 5: 'E2', 6: 'C2' }
            pitch_str = bass_line_pitches.get(closest_l_idx, "C3")

        return snapped_y, pitch_str, staff, True
    else:
        # 칸(Space) 음표: 상하 두 선의 정중앙으로 100% 자석 스냅
        space_idx = int(round((abs_y - (ref_lines[0] + half_sp)) / spacing))
        snapped_y = float(ref_lines[0] + half_sp + space_idx * spacing)

        if is_treble:
            # -1=G5, 0=E5 (Space 4), 1=C5 (Space 3), 2=A4 (Space 2), 3=F4 (Space 1), 4=D4, 5=B3, 6=G3
            treble_space_pitches = { -2: 'B5', -1: 'G5', 0: 'E5', 1: 'C5', 2: 'A4', 3: 'F4', 4: 'D4', 5: 'B3', 6: 'G3' }
            pitch_str = treble_space_pitches.get(space_idx, "D4")
        else:
            # -2=D4, -1=B3, 0=G3 (Space 4), 1=E3 (Space 3), 2=C3 (Space 2), 3=A2 (Space 1), 4=F2, 5=D2
            bass_space_pitches = { -2: 'D4', -1: 'B3', 0: 'G3', 1: 'E3', 2: 'C3', 3: 'A2', 4: 'F2', 5: 'D2', 6: 'B1' }
            pitch_str = bass_space_pitches.get(space_idx, "D3")

        return snapped_y, pitch_str, staff, False


def detect_pitch_from_y(
    y: float,
    treble_y_lines: Optional[List[int]] = None,
    bass_y_lines: Optional[List[int]] = None,
    line_spacing: float = 14.0,
    force_staff: Optional[int] = None
) -> Tuple[str, int]:
    """
    Y 픽셀 좌표로부터 5줄 오선지 선/칸 기준 음높이(Pitch Step & Octave: 예 C4, G4, E5) 및 staff 파트를 역산합니다.
    """
    t_lines = treble_y_lines if (treble_y_lines and len(treble_y_lines) >= 5) else [220, 234, 248, 262, 276]
    b_lines = bass_y_lines if (bass_y_lines and len(bass_y_lines) >= 5) else [350, 364, 378, 392, 406]
    spacing = line_spacing if line_spacing > 0 else 14.0
    half_sp = spacing / 2.0

    if force_staff == 2:
        staff = 2
        is_treble = False
    elif force_staff == 1:
        staff = 1
        is_treble = True
    else:
        split_y = (t_lines[4] + b_lines[0]) / 2.0
        is_treble = (y < split_y)
        staff = 1 if is_treble else 2

    ref_lines = t_lines if is_treble else b_lines
    
    # 선에 더 가까운지 칸에 더 가까운지 판별
    line_diff = abs(y - ref_lines[0]) % spacing
    is_line_bound = (line_diff < spacing * 0.28 or line_diff > spacing * 0.72)

    if is_line_bound:
        line_idx_diff = int(round((y - ref_lines[0]) / spacing))
        if is_treble:
            treble_line_pitches = { -2: 'C6', -1: 'A5', 0: 'F5', 1: 'D5', 2: 'B4', 3: 'G4', 4: 'E4', 5: 'C4', 6: 'A3', 7: 'F3' }
            pitch_str = treble_line_pitches.get(line_idx_diff, "C4")
        else:
            bass_line_pitches = { -2: 'E4', -1: 'C4', 0: 'A3', 1: 'F3', 2: 'D3', 3: 'B2', 4: 'G2', 5: 'E2', 6: 'C2' }
            pitch_str = bass_line_pitches.get(line_idx_diff, "C3")
    else:
        space_idx_diff = int(round((y - (ref_lines[0] + half_sp)) / spacing))
        if is_treble:
            treble_space_pitches = { -2: 'B5', -1: 'G5', 0: 'E5', 1: 'C5', 2: 'A4', 3: 'F4', 4: 'D4', 5: 'B3', 6: 'G3' }
            pitch_str = treble_space_pitches.get(space_idx_diff, "D4")
        else:
            bass_space_pitches = { -2: 'D4', -1: 'B3', 0: 'G3', 1: 'E3', 2: 'C3', 3: 'A2', 4: 'F2', 5: 'D2', 6: 'B1' }
            pitch_str = bass_space_pitches.get(space_idx_diff, "D3")

    return pitch_str, staff
