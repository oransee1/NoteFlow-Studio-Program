import math
import numpy as np
import xml.etree.ElementTree as ET
from typing import List, Dict, Tuple, Optional, Any

from core.pdf_renderer import PDFRenderer
from core.musicxml_parser import ParsedScore, MeasureData, NoteData
from utils.layout_detector import SheetLayoutDetector, SystemRegion, MeasureBox, StaffInfo

class PrecisionCalculator:
    """
    수동으로 조정한 마디 및 음표 위치를 바탕으로:
    1. 오선지 5줄(Line 1~5) 및 칸(Space 1~4) 기반 음계(Pitch: Step, Alter, Octave)
    2. 건반 위치(높은음자리표 Treble / 낮은음자리표 Bass / MIDI 번호)
    3. 마디 내 상대 위치 기반 정밀 박자(Beat Position) 및 음표 길이(Duration)
    4. 악보 이미지 상의 음표 머리(Notehead) 픽셀 서브픽셀 정밀 스냅
    5. 최종 MusicXML DOM 트리 100% 동기화
    를 수행하는 정밀 계산 엔진입니다.
    """
    def __init__(self, pdf_renderer: PDFRenderer, layout_detector: SheetLayoutDetector):
        self.pdf_renderer = pdf_renderer
        self.layout_detector = layout_detector

    def recalculate_score(self, score: ParsedScore, dpi: int = 200, snap_notehead_pixels: bool = True) -> Dict[str, Any]:
        """
        전체 악보의 모든 마디 및 음표에 대해 정밀 계산을 일괄 수행하고
        상세 분석 통계 및 최종 MusicXML 동기화 결과를 반환합니다.
        """
        if not score or not score.measures:
            return {"status": "empty", "measures_count": 0, "notes_count": 0}

        page_count = self.pdf_renderer.page_count if self.pdf_renderer.doc else 1
        
        # 1. 페이지별 시스템, 오선지 및 전체 이진화 이미지(thresh_full) 캐시 구성
        page_systems_map: Dict[int, Tuple[np.ndarray, np.ndarray, List[SystemRegion]]] = {}
        for p_idx in range(page_count):
            if self.pdf_renderer.doc and p_idx < self.pdf_renderer.page_count:
                bgr_img, _ = self.pdf_renderer.render_page_bgr(p_idx, dpi=dpi)
                import cv2
                gray = cv2.cvtColor(bgr_img, cv2.COLOR_BGR2GRAY)
                _, thresh_full = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
                systems = self.layout_detector.detect_staff_lines_and_systems(bgr_img)
                self.layout_detector.detect_barlines_and_measures(bgr_img, systems)
                page_systems_map[p_idx] = (bgr_img, thresh_full, systems)

        total_measures_processed = 0
        total_notes_processed = 0
        treble_notes_count = 0
        bass_notes_count = 0
        rests_count = 0
        pitch_changes_count = 0

        # 조표(Key Signature) 추적
        current_fifths = 0

        for m_data in score.measures:
            p_idx = m_data.mapped_page
            bgr_img, thresh_full, systems = page_systems_map.get(p_idx, (None, None, []))

            # 현재 마디의 fifths 추적
            if hasattr(m_data, 'fifths') and m_data.fifths is not None:
                current_fifths = m_data.fifths

            key_sig_map = self._get_key_signature_map(current_fifths)

            # 마디의 Y 위치에 가장 적합한 SystemRegion 탐색
            sys_region = self._find_matching_system(m_data, systems)

            m_stats = self._calculate_measure_precision(
                m_data=m_data,
                sys_region=sys_region,
                key_sig_map=key_sig_map,
                thresh_full=thresh_full if snap_notehead_pixels else None,
                dpi=dpi
            )

            total_measures_processed += 1
            total_notes_processed += m_stats["total_notes"]
            treble_notes_count += m_stats["treble_notes"]
            bass_notes_count += m_stats["bass_notes"]
            rests_count += m_stats["rests"]
            pitch_changes_count += m_stats["pitch_changes"]

        # 2. 최종 MusicXML DOM 트리 100% 동기화
        self.sync_xml_tree(score)

        return {
            "status": "success",
            "measures_count": total_measures_processed,
            "notes_count": total_notes_processed,
            "treble_count": treble_notes_count,
            "bass_count": bass_notes_count,
            "rests_count": rests_count,
            "pitch_changes": pitch_changes_count
        }

    def recalculate_single_measure(self, score: ParsedScore, m_data: MeasureData, dpi: int = 200, snap_notehead_pixels: bool = True) -> Dict[str, Any]:
        """
        단일 마디(m_data)에 대해 정밀 계산을 수행하고 MusicXML DOM 트리를 동기화합니다.
        """
        if not m_data:
            return {"status": "error", "message": "마디 데이터가 없습니다."}

        p_idx = m_data.mapped_page
        bgr_img = None
        thresh_full = None
        systems = []
        if self.pdf_renderer.doc and p_idx < self.pdf_renderer.page_count:
            bgr_img, _ = self.pdf_renderer.render_page_bgr(p_idx, dpi=dpi)
            import cv2
            gray = cv2.cvtColor(bgr_img, cv2.COLOR_BGR2GRAY)
            _, thresh_full = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
            systems = self.layout_detector.detect_staff_lines_and_systems(bgr_img)
            self.layout_detector.detect_barlines_and_measures(bgr_img, systems)

        # 조표 추적
        current_fifths = getattr(m_data, 'fifths', 0) or 0
        key_sig_map = self._get_key_signature_map(current_fifths)
        sys_region = self._find_matching_system(m_data, systems)

        m_stats = self._calculate_measure_precision(
            m_data=m_data,
            sys_region=sys_region,
            key_sig_map=key_sig_map,
            thresh_full=thresh_full if snap_notehead_pixels else None,
            dpi=dpi
        )

        self.sync_xml_tree(score)
        return m_stats

    def _find_matching_system(self, m_data: MeasureData, systems: List[SystemRegion]) -> Optional[SystemRegion]:
        if not systems:
            return None
        
        my = (m_data.bbox_y1 + m_data.bbox_y2) / 2.0 if (m_data.bbox_y1 is not None and m_data.bbox_y2 is not None) else (m_data.bbox_y1 or 0)
        
        best_sys = None
        min_dist = float('inf')
        for sys in systems:
            if sys.y_min - 40 <= my <= sys.y_max + 40:
                return sys
            dist = min(abs(my - sys.y_min), abs(my - sys.y_max))
            if dist < min_dist:
                min_dist = dist
                best_sys = sys

        return best_sys or systems[0]

    def _calculate_measure_precision(
        self,
        m_data: MeasureData,
        sys_region: Optional[SystemRegion],
        key_sig_map: Dict[str, str],
        thresh_full: Optional[np.ndarray] = None,
        dpi: int = 200
    ) -> Dict[str, int]:
        """
        마디 내의 모든 음표에 대해 사용자가 배치한 좌표를 안전하게 유지하면서,
        오선지 줄/칸(Line/Space) 서브픽셀 자석 스냅 및 음계/건반/박자 정밀 계산을 수행합니다.
        """
        if m_data.bbox_x1 is None or m_data.bbox_x2 is None:
            return {"total_notes": 0, "treble_notes": 0, "bass_notes": 0, "rests": 0, "pitch_changes": 0}

        x1 = float(min(m_data.bbox_x1, m_data.bbox_x2))
        x2 = float(max(m_data.bbox_x1, m_data.bbox_x2))
        y1 = float(m_data.bbox_y1 or 0)
        y2 = float(m_data.bbox_y2 or (y1 + 100))
        width = max(15.0, x2 - x1)

        # 오선지 정보 획득
        has_treble = sys_region is not None and sys_region.treble_staff is not None
        has_bass = sys_region is not None and sys_region.bass_staff is not None

        t_lines = sys_region.treble_staff.y_lines if has_treble else [int(y1 + 25 + i * 10) for i in range(5)]
        b_lines = sys_region.bass_staff.y_lines if has_bass else [int(t_lines[4] + 50 + i * 10) for i in range(5)]
        t_spacing = sys_region.treble_staff.line_spacing if has_treble else 10.0
        b_spacing = sys_region.bass_staff.line_spacing if has_bass else 10.0

        split_y = (t_lines[4] + b_lines[0]) / 2.0

        # 가로 박자 영역 패딩 계산
        is_first_in_sys = (sys_region and sys_region.barline_xs and abs(x1 - sys_region.barline_xs[0]) < 30) or (m_data.number == 1)
        left_pad = width * 0.22 if is_first_in_sys else width * 0.08
        right_pad = width * 0.05
        usable_width = max(10.0, width - left_pad - right_pad)

        from core.auto_aligner import snap_notehead_to_local_staff_line

        treble_notes = 0
        bass_notes = 0
        rests = 0
        pitch_changes = 0

        # 1단계: 사용자가 배치한 좌표를 존중하며 오선지 선/칸 서브픽셀 정밀 스냅 및 음계 계산
        for note in m_data.notes:
            nx = note.mapped_x if note.mapped_x is not None else (x1 + width * 0.5)
            ny = note.mapped_y if note.mapped_y is not None else ((y1 + y2) * 0.5)

            if note.is_rest or note.pitch == "Rest":
                note.is_rest = True
                note.pitch = "Rest"
                rests += 1
                if ny >= split_y and has_bass:
                    note.staff = 2
                else:
                    note.staff = 1
                continue

            # 음표 좌우 수평선(오선지 5줄 및 덧줄) 국소 스캔을 통한 선/칸 서브픽셀 자석 스냅
            snapped_y, pitch_raw, staff, _ = snap_notehead_to_local_staff_line(
                nx, ny, thresh_full, sys_region,
                custom_treble_lines=t_lines,
                custom_bass_lines=b_lines,
                custom_spacing=t_spacing
            )
            note.mapped_y = snapped_y
            note.staff = staff

            if staff == 1:
                treble_notes += 1
            else:
                bass_notes += 1

            # 기본 음계 문자(C, D, E, F, G, A, B) 및 옥타브 분리
            step_char = pitch_raw[0].upper()
            try:
                octave = int(pitch_raw[-1])
            except (ValueError, IndexError):
                octave = 4

            # 조표(Key Signature) 및 기존 임시표(Accidental) 반영
            acc = ""
            old_step = note.pitch[0].upper() if note.pitch and note.pitch != "Rest" else ""
            if old_step == step_char and ('#' in note.pitch or 'b' in note.pitch):
                # 기존에 같은 음에 붙어있던 임시표 유지
                if '#' in note.pitch: acc = "#"
                elif 'b' in note.pitch: acc = "b"
            elif step_char in key_sig_map:
                # 조표 적용
                acc = key_sig_map[step_char]

            calc_pitch = f"{step_char}{acc}{octave}"
            if calc_pitch != note.pitch:
                pitch_changes += 1
                note.pitch = calc_pitch

        # 2단계: 가로 위치 기반 박자(Beat Position) 및 길이(Duration) 계산
        total_beats = max(1.0, float(m_data.beats))
        divisions = max(1, m_data.divisions)

        for note in m_data.notes:
            nx = note.mapped_x if note.mapped_x is not None else (x1 + width * 0.5)
            rel_x = nx - (x1 + left_pad)
            ratio = max(0.0, min(1.0, rel_x / usable_width))
            raw_beat = ratio * total_beats

            # 음악적 서브디비전 양자화 (Quantization Grid: 16분음표, 8분 셋잇단, 8분음표, 4분음표 등)
            quantized_beat = self._quantize_beat(raw_beat, total_beats)
            note.beat_position = quantized_beat

        # 3단계: 파트별(Staff별) 시간순 정렬 및 음표 길이(Duration) 정밀 산정
        for st_val in (1, 2):
            st_notes = [n for n in m_data.notes if n.staff == st_val]
            if not st_notes:
                continue

            # beat_position 순서로 정렬
            st_notes.sort(key=lambda n: n.beat_position)

            # 유니크한 온셋(Onset) 시점들 추출
            unique_onsets = sorted(list(set(n.beat_position for n in st_notes)))
            onset_to_dur_beats: Dict[float, float] = {}

            for idx, onset in enumerate(unique_onsets):
                if idx + 1 < len(unique_onsets):
                    next_onset = unique_onsets[idx + 1]
                    dur_b = max(0.25, next_onset - onset)
                else:
                    # 마디의 마지막 음표: 남은 박자 할당 (최소 0.25박)
                    dur_b = max(0.25, total_beats - onset)
                onset_to_dur_beats[onset] = dur_b

            # duration(divisions 단위) 할당
            for n in st_notes:
                dur_b = onset_to_dur_beats.get(n.beat_position, 1.0)
                n.duration = max(1, int(round(dur_b * divisions)))

        # 4단계: 음표 인덱스 재정렬 (사용자가 배치한 모든 음표 100% 보존)
        for i, n in enumerate(m_data.notes):
            n.note_index = i

        return {
            "total_notes": len(m_data.notes),
            "treble_notes": treble_notes,
            "bass_notes": bass_notes,
            "rests": rests,
            "pitch_changes": pitch_changes
        }

    def _quantize_beat(self, raw_beat: float, total_beats: float) -> float:
        """
        연속적인 박자 값을 16분음표(0.25), 8분 셋잇단음표(0.333/0.667), 8분음표(0.5), 점음표 그리드로 스마트 양자화합니다.
        """
        # 기본 그리드 후보 생성
        candidates = []
        b = 0.0
        while b <= total_beats + 0.01:
            candidates.extend([
                b,
                b + 0.25,
                b + 1.0 / 3.0,
                b + 0.375,
                b + 0.5,
                b + 2.0 / 3.0,
                b + 0.75,
                b + 0.875
            ])
            b += 1.0

        candidates = sorted(list(set([round(c, 4) for c in candidates if c <= total_beats])))

        best_cand = raw_beat
        min_diff = 0.16  # 스냅 허용 오차 (0.16 박 이내이면 그리드에 착 붙임)

        for c in candidates:
            diff = abs(raw_beat - c)
            if diff < min_diff:
                min_diff = diff
                best_cand = c

        return round(best_cand, 3)

    def _get_key_signature_map(self, fifths: int) -> Dict[str, str]:
        """
        MusicXML fifths 값(-7 ~ +7)에 따른 플랫/샵 임시표 매핑 딕셔너리를 반환합니다.
        """
        sharps_order = ['F', 'C', 'G', 'D', 'A', 'E', 'B']
        flats_order = ['B', 'E', 'A', 'D', 'G', 'C', 'F']

        result = {}
        if fifths > 0:
            for i in range(min(7, fifths)):
                result[sharps_order[i]] = "#"
        elif fifths < 0:
            for i in range(min(7, abs(fifths))):
                result[flats_order[i]] = "b"
        return result

    def sync_xml_tree(self, score: ParsedScore):
        """
        계산된 모든 마디/음표(Pitch, Staff, Duration, Voice, BBox, Coordinates, System/Page breaks)를
        MusicXML ElementTree DOM에 100% 완벽 동기화합니다.
        """
        if score.xml_tree is None or score.root_element is None:
            return

        measure_map = {m.number: m for m in score.measures}

        for part in score.root_element.findall("part"):
            prev_m_data = None
            for m_elem in part.findall("measure"):
                m_num_str = m_elem.get("number", "0")
                try:
                    m_num = int(m_num_str)
                except ValueError:
                    continue

                if m_num not in measure_map:
                    continue

                m_data = measure_map[m_num]

                # 마디 width 및 커스텀 메타데이터
                if m_data.bbox_x1 is not None and m_data.bbox_x2 is not None:
                    calc_w = abs(m_data.bbox_x2 - m_data.bbox_x1) * (72.0 / 200.0)
                    m_elem.set("width", f"{calc_w:.2f}")

                m_elem.set("nf-page", str(m_data.mapped_page))
                if m_data.bbox_x1 is not None: m_elem.set("nf-bbox-x1", f"{m_data.bbox_x1:.2f}")
                if m_data.bbox_y1 is not None: m_elem.set("nf-bbox-y1", f"{m_data.bbox_y1:.2f}")
                if m_data.bbox_x2 is not None: m_elem.set("nf-bbox-x2", f"{m_data.bbox_x2:.2f}")
                if m_data.bbox_y2 is not None: m_elem.set("nf-bbox-y2", f"{m_data.bbox_y2:.2f}")

                # 표준 MusicXML print (new-system / new-page) 주입
                is_new_page = False
                is_new_system = False

                if prev_m_data is None:
                    is_new_system = True
                    is_new_page = True
                elif m_data.mapped_page > prev_m_data.mapped_page:
                    is_new_page = True
                elif m_data.mapped_page == prev_m_data.mapped_page:
                    dy = (m_data.bbox_y1 or 0.0) - (prev_m_data.bbox_y1 or 0.0)
                    dx = (m_data.bbox_x1 or 0.0) - (prev_m_data.bbox_x1 or 0.0)
                    if abs(dy) > 35.0 or dx < -50.0 or m_data.new_system:
                        is_new_system = True

                print_elem = m_elem.find("print")
                if is_new_page or is_new_system:
                    if print_elem is None:
                        print_elem = ET.Element("print")
                        m_elem.insert(0, print_elem)
                    if is_new_page:
                        print_elem.set("new-page", "yes")
                    elif "new-page" in print_elem.attrib:
                        del print_elem.attrib["new-page"]

                    if is_new_system:
                        print_elem.set("new-system", "yes")
                    elif "new-system" in print_elem.attrib:
                        del print_elem.attrib["new-system"]

                prev_m_data = m_data

                # 음표 노드 1:1 동기화
                note_nodes = m_elem.findall("note")
                m_notes_dict = {n.id: n for n in m_data.notes}
                matched_note_ids = set()

                for idx, n_elem in enumerate(note_nodes):
                    n_id = n_elem.get("nf-id")
                    matching_note = None
                    if n_id and n_id in m_notes_dict:
                        matching_note = m_notes_dict[n_id]
                    elif idx < len(m_data.notes):
                        matching_note = m_data.notes[idx]
                        n_elem.set("nf-id", matching_note.id)

                    if matching_note:
                        matched_note_ids.add(matching_note.id)
                        self._sync_single_note_elem(n_elem, matching_note, m_data)
                    else:
                        m_elem.remove(n_elem)

                # XML 엘리먼트가 아직 없는 새로 추가된 음표들에 대해 <note> 엘리먼트 생성 및 추가
                for note_data in m_data.notes:
                    if note_data.id not in matched_note_ids:
                        new_n_elem = ET.Element("note")
                        new_n_elem.set("nf-id", note_data.id)
                        self._sync_single_note_elem(new_n_elem, note_data, m_data)
                        m_elem.append(new_n_elem)

    def _sync_single_note_elem(self, n_elem: ET.Element, note_data: NoteData, m_data: MeasureData):
        """단일 note XML 엘리먼트의 pitch, alter, octave, rest, duration, staff, default-x/y 갱신"""
        # 1. Rest vs Pitch
        if note_data.is_rest or note_data.pitch == "Rest":
            p_elem = n_elem.find("pitch")
            if p_elem is not None:
                n_elem.remove(p_elem)
            if n_elem.find("rest") is None:
                n_elem.insert(0, ET.Element("rest"))
        else:
            r_elem = n_elem.find("rest")
            if r_elem is not None:
                n_elem.remove(r_elem)

            p_elem = n_elem.find("pitch")
            if p_elem is None:
                p_elem = ET.Element("pitch")
                n_elem.insert(0, p_elem)

            # Step
            step_elem = p_elem.find("step")
            if step_elem is None:
                step_elem = ET.SubElement(p_elem, "step")
            step_elem.text = note_data.pitch[0].upper() if note_data.pitch else "C"

            # Alter
            alter_elem = p_elem.find("alter")
            if '#' in note_data.pitch:
                if alter_elem is None:
                    alter_elem = ET.SubElement(p_elem, "alter")
                alter_elem.text = "1"
            elif 'b' in note_data.pitch:
                if alter_elem is None:
                    alter_elem = ET.SubElement(p_elem, "alter")
                alter_elem.text = "-1"
            else:
                if alter_elem is not None:
                    p_elem.remove(alter_elem)

            # Octave
            oct_elem = p_elem.find("octave")
            if oct_elem is None:
                oct_elem = ET.SubElement(p_elem, "octave")
            oct_char = note_data.pitch[-1] if (note_data.pitch and note_data.pitch[-1].isdigit()) else "4"
            oct_elem.text = oct_char

        # 2. Staff
        staff_elem = n_elem.find("staff")
        if staff_elem is None:
            staff_elem = ET.SubElement(n_elem, "staff")
        staff_elem.text = str(note_data.staff)

        # 3. Duration
        if note_data.duration > 0:
            dur_elem = n_elem.find("duration")
            if dur_elem is None:
                dur_elem = ET.SubElement(n_elem, "duration")
            dur_elem.text = str(note_data.duration)

        # 4. Voice
        voice_elem = n_elem.find("voice")
        if voice_elem is None:
            voice_elem = ET.SubElement(n_elem, "voice")
        voice_elem.text = str(note_data.voice)

        # 5. 좌표 메타데이터
        if note_data.mapped_x is not None:
            rel_x = (note_data.mapped_x - (m_data.bbox_x1 or 0)) * (72.0 / 200.0)
            rel_y = (note_data.mapped_y - (m_data.bbox_y1 or 0)) * (72.0 / 200.0)
            n_elem.set("default-x", f"{rel_x:.2f}")
            n_elem.set("default-y", f"{rel_y:.2f}")
            n_elem.set("nf-mapped-x", f"{note_data.mapped_x:.2f}")
            n_elem.set("nf-mapped-y", f"{note_data.mapped_y:.2f}")
            n_elem.set("nf-page", str(note_data.mapped_page))
