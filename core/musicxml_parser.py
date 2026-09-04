import xml.etree.ElementTree as ET
import os
import zipfile
import uuid
import math
from dataclasses import dataclass, field
from typing import List, Optional, Dict

@dataclass
class NoteData:
    id: str
    measure_number: int
    note_index: int
    pitch: str           # 예: 'C4', 'G#5', 'Rest'
    is_rest: bool
    duration: int        # divisions 단위
    beat_position: float # 마디 시작 기준 박자 (0.0, 1.0, 2.0 ...)
    voice: int = 1
    staff: int = 1
    default_x: Optional[float] = None
    default_y: Optional[float] = None
    # 맵핑 결과 보정 좌표 (PDF 픽셀 좌표계)
    mapped_x: Optional[float] = None
    mapped_y: Optional[float] = None
    mapped_page: int = 0

@dataclass
class MeasureData:
    number: int
    time_signature: str = "4/4"
    beats: int = 4
    beat_type: int = 4
    divisions: int = 1
    fifths: int = 0
    width: Optional[float] = None
    new_system: bool = False
    new_page: bool = False
    notes: List[NoteData] = field(default_factory=list)
    # PDF 맵핑 결과 좌표 (마디 bounding box)
    mapped_page: int = 0
    bbox_x1: Optional[float] = None
    bbox_y1: Optional[float] = None
    bbox_x2: Optional[float] = None
    bbox_y2: Optional[float] = None

@dataclass
class ParsedScore:
    title: str
    composer: str
    total_measures: int
    measures: List[MeasureData] = field(default_factory=list)
    xml_tree: Optional[ET.ElementTree] = None
    root_element: Optional[ET.Element] = None

class MusicXMLParser:
    def __init__(self):
        self.parsed_score: Optional[ParsedScore] = None

    @staticmethod
    def is_duplicate_note(n1: NoteData, n2: NoteData) -> bool:
        """
        두 음표가 물리적으로 동일한 위치(쓰레기 중복 점)인지 판별합니다.
        화음(동일 X축, 다른 Y축/피치)은 100% 정상 보존합니다.
        """
        # 1. 동일 고유 ID인 경우 무조건 중복
        if n1.id and n2.id and n1.id == n2.id:
            return True

        # 2. 픽셀 좌표계(mapped_x, mapped_y)가 존재하는 경우
        if n1.mapped_x is not None and n2.mapped_x is not None and n1.mapped_y is not None and n2.mapped_y is not None:
            dx = abs(n1.mapped_x - n2.mapped_x)
            dy = abs(n1.mapped_y - n2.mapped_y)
            dist = math.hypot(dx, dy)

            # 4.8px 이내 초밀착: 물리적으로 동일한 음표 머리(타원 직경 11~13px) 중심 영역 내의 중복 점
            if dist <= 4.8 or (dx <= 2.5 and dy <= 4.8):
                return True

            # 동일 피치인데 6.0px 이내인 경우 (단일 음표의 다중 스냅 잔재)
            if dist <= 6.0 and n1.pitch == n2.pitch:
                return True

            # 한쪽이 쉼표(Rest)이고 6.0px 이내 겹치는 경우
            if dist <= 6.0 and (n1.is_rest or n2.is_rest or n1.pitch == "Rest" or n2.pitch == "Rest"):
                return True

        # 3. default-x, default-y 기준 (픽셀 좌표 매핑 전인 경우)
        elif n1.default_x is not None and n2.default_x is not None and n1.default_y is not None and n2.default_y is not None:
            scale = 200.0 / 72.0
            dx = abs(n1.default_x - n2.default_x) * scale
            dy = abs(n1.default_y - n2.default_y) * scale
            dist = math.hypot(dx, dy)
            if dist <= 4.8 or (dist <= 6.0 and n1.pitch == n2.pitch):
                return True
            if dist <= 6.0 and (n1.is_rest or n2.is_rest or n1.pitch == "Rest" or n2.pitch == "Rest"):
                return True

        # 4. 박자(beat_position) 및 오선/피치 기준
        if abs(n1.beat_position - n2.beat_position) < 0.02 and n1.staff == n2.staff:
            if n1.pitch == n2.pitch:
                if n1.default_x is None or n2.default_x is None or abs(n1.default_x - n2.default_x) < 2.0:
                    return True
            elif (n1.is_rest or n1.pitch == "Rest") or (n2.is_rest or n2.pitch == "Rest"):
                if n1.default_x is None or n2.default_x is None or abs(n1.default_x - n2.default_x) < 2.0:
                    return True

        return False

    @classmethod
    def deduplicate_measure_notes(cls, m_data: MeasureData, m_elem: Optional[ET.Element] = None) -> int:
        """
        마디 내의 중복 음표를 정리하여 동일 위치에 1개만 남기고 삭제합니다.
        화음(다른 피치/Y좌표)은 안전하게 보존하며, 쉼표 위에 실제 음표가 겹칠 경우 실제 음표를 유지합니다.
        m_elem(XML 엘리먼트)이 제공되면 XML 트리에서도 삭제된 음표 엘리먼트를 즉시 제거합니다.
        제거된 중복 음표 개수를 반환합니다.
        """
        if not m_data or not m_data.notes:
            return 0

        measure_beats = float(getattr(m_data, 'beats', 4) or 4)
        unique_notes: List[NoteData] = []
        removed_ids = set()

        for note in m_data.notes:
            dup_idx = -1
            for idx, u_note in enumerate(unique_notes):
                if cls.is_duplicate_note(note, u_note):
                    dup_idx = idx
                    break

            if dup_idx >= 0:
                u_note = unique_notes[dup_idx]
                u_is_rest = u_note.is_rest or u_note.pitch == "Rest"
                n_is_rest = note.is_rest or note.pitch == "Rest"

                # 1. 쉼표 vs 실제 음표: 실제 음표 우선 보존
                if u_is_rest and not n_is_rest:
                    removed_ids.add(u_note.id)
                    unique_notes[dup_idx] = note
                elif not u_is_rest and n_is_rest:
                    removed_ids.add(note.id)
                else:
                    # 2. 둘 다 음표이거나 둘 다 쉼표인 경우:
                    # 마디 박자 범위(measure_beats) 초과 여부 확인 (비정상 박자의 추가 점은 우선 삭제)
                    u_out = u_note.beat_position > measure_beats + 0.05
                    n_out = note.beat_position > measure_beats + 0.05
                    if u_out and not n_out:
                        removed_ids.add(u_note.id)
                        unique_notes[dup_idx] = note
                    else:
                        removed_ids.add(note.id)
            else:
                unique_notes.append(note)

        removed_count = len(m_data.notes) - len(unique_notes)
        for i, n in enumerate(unique_notes):
            n.note_index = i
        m_data.notes = unique_notes

        # XML 엘리먼트 동기화 (전달된 경우)
        if m_elem is not None:
            seen_ids = set()
            for note_elem in list(m_elem.findall("note")):
                nid = note_elem.get("nf-id")
                if nid in removed_ids or nid in seen_ids:
                    m_elem.remove(note_elem)
                elif nid:
                    seen_ids.add(nid)

        return removed_count

    def parse(self, xml_path: str) -> ParsedScore:
        """MusicXML 파일 (.xml, .musicxml, .mxl)을 읽고 구조화된 데이터로 파싱합니다."""
        target_path = xml_path

        # .mxl (zip 압축된 MusicXML) 처리
        if xml_path.lower().endswith('.mxl'):
            target_path = self._extract_mxl(xml_path)

        tree = ET.parse(target_path)
        root = tree.getroot()

        title = ""
        composer = ""
        movement_title = root.findtext("movement-title")
        if movement_title:
            title = movement_title
        else:
            work_title = root.findtext("work/work-title")
            if work_title:
                title = work_title

        creator = root.findtext("identification/creator")
        if creator:
            composer = creator

        # 파트(part) 추출 - 기본적으로 첫 번째 피아노/독주 파트를 기본 축으로 사용
        measures_dict: Dict[int, MeasureData] = {}
        
        # divisions & time signature & key signature 추적
        current_divisions = 1
        current_beats = 4
        current_beat_type = 4
        current_fifths = 0

        for part in root.findall("part"):
            for m_elem in part.findall("measure"):
                m_num_str = m_elem.get("number", "0")
                try:
                    m_num = int(m_num_str)
                except ValueError:
                    m_num = len(measures_dict) + 1

                # 속성 (divisions, time signature, key)
                attribs = m_elem.find("attributes")
                if attribs is not None:
                    div_elem = attribs.find("divisions")
                    if div_elem is not None and div_elem.text:
                        current_divisions = int(div_elem.text)
                    time_elem = attribs.find("time")
                    if time_elem is not None:
                        beats_elem = time_elem.find("beats")
                        beat_type_elem = time_elem.find("beat-type")
                        if beats_elem is not None and beats_elem.text:
                            current_beats = int(beats_elem.text)
                        if beat_type_elem is not None and beat_type_elem.text:
                            current_beat_type = int(beat_type_elem.text)
                    key_elem = attribs.find("key")
                    if key_elem is not None:
                        f_elem = key_elem.find("fifths")
                        if f_elem is not None and f_elem.text:
                            try:
                                current_fifths = int(f_elem.text)
                            except ValueError:
                                pass

                time_sig = f"{current_beats}/{current_beat_type}"
                width_val = m_elem.get("width")
                width = float(width_val) if width_val else None

                # 시스템 / 페이지 줄바꿈 검사
                print_elem = m_elem.find("print")
                new_system = False
                new_page = False
                if print_elem is not None:
                    if print_elem.get("new-system") == "yes":
                        new_system = True
                    if print_elem.get("new-page") == "yes":
                        new_page = True

                # 불필요한 재생/사운드 전용 쓰레기 데이터만 안전하게 필터링 (print 태그는 레이아웃에 필수이므로 임의 삭제하지 않음)
                for garbage_tag in ["sound", "harmony", "grouping", "figure"]:
                    for garbage in m_elem.findall(garbage_tag):
                        m_elem.remove(garbage)

                # 커스텀 맵핑 속성 추출 (NoteFlow Studio)
                nf_m_page = m_elem.get("nf-page")
                nf_x1 = m_elem.get("nf-bbox-x1")
                nf_y1 = m_elem.get("nf-bbox-y1")
                nf_x2 = m_elem.get("nf-bbox-x2")
                nf_y2 = m_elem.get("nf-bbox-y2")

                parsed_m_page = int(nf_m_page) if (nf_m_page is not None and nf_m_page != "") else 0
                parsed_bbox_x1 = None
                parsed_bbox_y1 = None
                parsed_bbox_x2 = None
                parsed_bbox_y2 = None
                try:
                    if nf_x1:
                        v = float(nf_x1)
                        if not (math.isnan(v) or math.isinf(v) or abs(v) > 50000.0): parsed_bbox_x1 = v
                    if nf_y1:
                        v = float(nf_y1)
                        if not (math.isnan(v) or math.isinf(v) or abs(v) > 50000.0): parsed_bbox_y1 = v
                    if nf_x2:
                        v = float(nf_x2)
                        if not (math.isnan(v) or math.isinf(v) or abs(v) > 50000.0): parsed_bbox_x2 = v
                    if nf_y2:
                        v = float(nf_y2)
                        if not (math.isnan(v) or math.isinf(v) or abs(v) > 50000.0): parsed_bbox_y2 = v
                except (ValueError, TypeError):
                    pass

                if m_num not in measures_dict:
                    measures_dict[m_num] = MeasureData(
                        number=m_num,
                        time_signature=time_sig,
                        beats=current_beats,
                        beat_type=current_beat_type,
                        divisions=current_divisions,
                        fifths=current_fifths,
                        width=width,
                        new_system=new_system,
                        new_page=new_page,
                        mapped_page=parsed_m_page,
                        bbox_x1=parsed_bbox_x1,
                        bbox_y1=parsed_bbox_y1,
                        bbox_x2=parsed_bbox_x2,
                        bbox_y2=parsed_bbox_y2,
                        notes=[]
                    )

                measure_obj = measures_dict[m_num]
                if new_system:
                    measure_obj.new_system = True
                if new_page:
                    measure_obj.new_page = True

                # 음표 파싱
                current_onset = 0.0
                note_idx = 0

                for note_elem in m_elem.findall("note"):
                    # chord인 경우 onset은 이전 음표와 동일
                    is_chord = note_elem.find("chord") is not None
                    
                    dur_elem = note_elem.find("duration")
                    dur = int(dur_elem.text) if dur_elem is not None and dur_elem.text else 0

                    if is_chord and len(measure_obj.notes) > 0:
                        beat_pos = measure_obj.notes[-1].beat_position
                    else:
                        beat_pos = current_onset / max(1, current_divisions)
                        current_onset += dur

                    is_rest = note_elem.find("rest") is not None
                    pitch_str = "Rest"
                    if not is_rest:
                        pitch_elem = note_elem.find("pitch")
                        if pitch_elem is not None:
                            step = pitch_elem.findtext("step", "C")
                            alter = pitch_elem.findtext("alter", "0")
                            octave = pitch_elem.findtext("octave", "4")
                            acc = ""
                            if alter == "1": acc = "#"
                            elif alter == "-1": acc = "b"
                            pitch_str = f"{step}{acc}{octave}"

                    def_x = note_elem.get("default-x")
                    def_y = note_elem.get("default-y")
                    
                    nf_n_page = note_elem.get("nf-page")
                    nf_mapped_x = note_elem.get("nf-mapped-x")
                    nf_mapped_y = note_elem.get("nf-mapped-y")

                    parsed_note_page = int(nf_n_page) if (nf_n_page is not None and nf_n_page != "") else parsed_m_page
                    parsed_note_x = None
                    parsed_note_y = None
                    parsed_def_x = None
                    parsed_def_y = None
                    try:
                        if nf_mapped_x:
                            v = float(nf_mapped_x)
                            if not (math.isnan(v) or math.isinf(v) or abs(v) > 50000.0): parsed_note_x = v
                        if nf_mapped_y:
                            v = float(nf_mapped_y)
                            if not (math.isnan(v) or math.isinf(v) or abs(v) > 50000.0): parsed_note_y = v
                        if def_x:
                            v = float(def_x)
                            if not (math.isnan(v) or math.isinf(v) or abs(v) > 50000.0): parsed_def_x = v
                        if def_y:
                            v = float(def_y)
                            if not (math.isnan(v) or math.isinf(v) or abs(v) > 50000.0): parsed_def_y = v
                    except (ValueError, TypeError):
                        pass

                    voice_elem = note_elem.find("voice")
                    voice = int(voice_elem.text) if voice_elem is not None and voice_elem.text else 1
                    
                    staff_elem = note_elem.find("staff")
                    staff = int(staff_elem.text) if staff_elem is not None and staff_elem.text else 1

                    # nf-id를 통해 XML 엘리먼트와 NoteData 간의 영구적인 1:1 매핑 (멀티 파트 꼬임 완벽 방지)
                    nf_id = note_elem.get("nf-id")
                    if not nf_id:
                        nf_id = f"m{m_num}_n{note_idx}_{uuid.uuid4().hex[:6]}"
                        note_elem.set("nf-id", nf_id)

                    note_obj = NoteData(
                        id=nf_id,
                        measure_number=m_num,
                        note_index=note_idx,
                        pitch=pitch_str,
                        is_rest=is_rest,
                        duration=dur,
                        beat_position=beat_pos,
                        voice=voice,
                        staff=staff,
                        default_x=parsed_def_x,
                        default_y=parsed_def_y,
                        mapped_page=parsed_note_page,
                        mapped_x=parsed_note_x,
                        mapped_y=parsed_note_y
                    )
                    measure_obj.notes.append(note_obj)
                    note_idx += 1

        # 마디별 동일 위치 중복 음표 정제 및 XML 트리 동기화 (불러올 때 동일 위치 음표 1개만 남기고 삭제)
        for m in measures_dict.values():
            self.deduplicate_measure_notes(m)

        # XML 엘리먼트에서도 삭제된 음표 동기화 제거
        for part in root.findall("part"):
            for m_elem in part.findall("measure"):
                try:
                    mn = int(m_elem.get("number", "0"))
                except ValueError:
                    continue
                if mn in measures_dict:
                    valid_ids = {n.id for n in measures_dict[mn].notes}
                    seen_ids = set()
                    for n_elem in list(m_elem.findall("note")):
                        nid = n_elem.get("nf-id")
                        if nid and (nid not in valid_ids or nid in seen_ids):
                            m_elem.remove(n_elem)
                        elif nid:
                            seen_ids.add(nid)

        sorted_measures = [measures_dict[k] for k in sorted(measures_dict.keys())]

        # 모든 음표가 staff == 1인 경우, 피치(Octave < 4) 기반으로 낮은음자리표(staff = 2) 자동 분할
        all_notes = [n for m in sorted_measures for n in m.notes if not n.is_rest]
        if all_notes and all(n.staff == 1 for n in all_notes):
            for n in all_notes:
                try:
                    oct_val = int(n.pitch[-1])
                    if oct_val < 4 or (oct_val == 4 and n.pitch[0] in ('C', 'D')):
                        n.staff = 2
                except (ValueError, IndexError):
                    pass

        score = ParsedScore(
            title=title or "Untitled",
            composer=composer or "Unknown",
            total_measures=len(sorted_measures),
            measures=sorted_measures,
            xml_tree=tree,
            root_element=root
        )
        self.parsed_score = score
        return score

    def distribute_measures_across_pages(self, score: ParsedScore, page_count: int, dpi: int = 200, pdf_renderer = None):
        """
        PDF 총 페이지 수 및 악보 레이아웃에 맞춰 MusicXML 마디 및 음표 좌표를 정밀 배치/복원합니다.
        저장된 커스텀 좌표(nf-bbox-x1 등)가 존재하는 경우 100% 그대로 완벽 보존합니다.
        """
        if not score or not score.measures or page_count <= 0:
            return

        # 1. 커스텀 맵핑 좌표 존재 여부 확인
        custom_mapped_measures = [m for m in score.measures if m.bbox_x1 is not None and m.bbox_x2 is not None]
        has_custom_mapping = len(custom_mapped_measures) > 0
        all_custom_mapped = len(custom_mapped_measures) == len(score.measures)

        # 2. new-page 태그 존재 여부 확인
        has_new_page_tags = any(m.new_page for m in score.measures)

        # 페이지 크기 계산
        pw, ph = 1200.0, 1600.0
        if pdf_renderer and pdf_renderer.doc:
            w, h = pdf_renderer.get_page_size(0)
            scale = dpi / 72.0
            pw, ph = w * scale, h * scale

        if not has_custom_mapping:
            # 커스텀 맵핑이 아예 없는 순수 MusicXML 파일인 경우:
            # new-page 및 new-system 태그를 최대한 활용하여 페이지/시스템별 정갈한 초기 배치
            current_page = 0
            current_sys = 0
            current_col_in_sys = 0
            measures_per_sys = 3  # 기본 1줄 3~4마디
            
            # 페이지별 마디 수 계산
            total_m = len(score.measures)
            measures_per_page = max(1, (total_m + page_count - 1) // page_count) if not has_new_page_tags else 0

            for idx, m in enumerate(score.measures):
                if has_new_page_tags:
                    if m.new_page and idx > 0:
                        current_page = min(page_count - 1, current_page + 1)
                        current_sys = 0
                        current_col_in_sys = 0
                    elif m.new_system and idx > 0:
                        current_sys += 1
                        current_col_in_sys = 0
                else:
                    new_p = min(page_count - 1, idx // measures_per_page)
                    if new_p != current_page:
                        current_page = new_p
                        current_sys = 0
                        current_col_in_sys = 0

                m.mapped_page = current_page

                # 시스템(줄) 줄바꿈 계산
                if current_col_in_sys >= measures_per_sys:
                    current_sys += 1
                    current_col_in_sys = 0

                # 시스템 내 마디 너비 및 위치 계산
                margin_x = pw * 0.07
                usable_pw = pw * 0.86
                m_w = usable_pw / float(measures_per_sys)
                sys_top = ph * 0.12 + current_sys * (ph * 0.14)
                sys_h = ph * 0.11

                m.bbox_x1 = margin_x + current_col_in_sys * m_w
                m.bbox_x2 = m.bbox_x1 + m_w - 6.0
                m.bbox_y1 = sys_top
                m.bbox_y2 = sys_top + sys_h

                current_col_in_sys += 1
        else:
            # 커스텀 맵핑이 이미 존재하는 경우:
            # 1단계: 기존 유효한 마디들의 page 범위를 clamp만 수행 (좌표는 절대 변경 금지!)
            for m in score.measures:
                if m.bbox_x1 is not None and m.bbox_x2 is not None:
                    m.mapped_page = min(page_count - 1, max(0, m.mapped_page))

            # 2단계: 만약 일부 마디만 bbox가 누락된 경우, 인접 마디의 위치를 이어받아 매끄럽게 연속 배치 (겹침 원천 방지)
            for idx, m in enumerate(score.measures):
                if m.bbox_x1 is None or m.bbox_x2 is None:
                    # 이전 마디 참조
                    prev_m = score.measures[idx - 1] if idx > 0 else None
                    next_m = score.measures[idx + 1] if idx + 1 < len(score.measures) else None
                    
                    ref_m = prev_m if (prev_m and prev_m.bbox_x1 is not None) else next_m
                    if ref_m and ref_m.bbox_x1 is not None:
                        m.mapped_page = ref_m.mapped_page
                        ref_w = max(50.0, (ref_m.bbox_x2 or 200.0) - (ref_m.bbox_x1 or 0.0))
                        ref_h = max(50.0, (ref_m.bbox_y2 or 200.0) - (ref_m.bbox_y1 or 0.0))
                        
                        if prev_m and prev_m.bbox_x2 is not None:
                            cand_x1 = prev_m.bbox_x2 + 2.0
                            if cand_x1 + ref_w > pw * 0.95:
                                # 줄바꿈
                                m.bbox_x1 = pw * 0.07
                                m.bbox_x2 = m.bbox_x1 + ref_w
                                m.bbox_y1 = (prev_m.bbox_y1 or 0.0) + ref_h + 30.0
                                m.bbox_y2 = m.bbox_y1 + ref_h
                            else:
                                m.bbox_x1 = cand_x1
                                m.bbox_x2 = cand_x1 + ref_w
                                m.bbox_y1 = prev_m.bbox_y1
                                m.bbox_y2 = prev_m.bbox_y2
                        elif next_m and next_m.bbox_x1 is not None:
                            m.bbox_x1 = max(pw * 0.07, (next_m.bbox_x1 or 0.0) - ref_w - 2.0)
                            m.bbox_x2 = next_m.bbox_x1 - 2.0
                            m.bbox_y1 = next_m.bbox_y1
                            m.bbox_y2 = next_m.bbox_y2
                    else:
                        m.mapped_page = 0
                        m.bbox_x1 = pw * 0.08
                        m.bbox_x2 = pw * 0.28
                        m.bbox_y1 = ph * 0.12
                        m.bbox_y2 = ph * 0.23

        # 3. 음표 좌표 동기화 (이미 저장된 mapped_x/y는 100% 보존!)
        for m in score.measures:
            bx1 = m.bbox_x1 or 0.0
            bx2 = m.bbox_x2 or (bx1 + 150.0)
            by1 = m.bbox_y1 or 0.0
            by2 = m.bbox_y2 or (by1 + 100.0)
            mw = max(10.0, bx2 - bx1)
            total_b = max(1.0, float(getattr(m, 'beats', 4) or 4))

            for n_idx, note in enumerate(m.notes):
                note.mapped_page = m.mapped_page

                # 이미 유효한 음표 절대 좌표(nf-mapped-x, nf-mapped-y)가 존재한다면 덮어쓰지 않고 100% 보존!
                if note.mapped_x is not None and note.mapped_y is not None:
                    continue

                scale = dpi / 72.0
                if note.default_x is not None and note.default_x > 0:
                    note.mapped_x = bx1 + (note.default_x * scale)
                elif hasattr(note, 'beat_position') and note.beat_position is not None:
                    ratio = min(1.0, max(0.0, note.beat_position / total_b))
                    note.mapped_x = bx1 + mw * (0.12 + 0.80 * ratio)
                else:
                    note.mapped_x = bx1 + ((n_idx + 0.5) / max(1, len(m.notes))) * mw

                if note.default_y is not None and note.default_y != 0:
                    note.mapped_y = by1 + (note.default_y * scale)
                else:
                    # 기본 오선지 중앙 배치 (높은음자리 vs 낮은음자리)
                    if note.staff == 2:
                        note.mapped_y = by1 + (by2 - by1) * 0.72
                    elif note.is_rest:
                        note.mapped_y = (by1 + by2) / 2.0
                    else:
                        note.mapped_y = by1 + (by2 - by1) * 0.35

        # 4. NaN / Inf 좌표 안전 클린업
        import math
        for m in score.measures:
            for attr in ['bbox_x1', 'bbox_y1', 'bbox_x2', 'bbox_y2']:
                val = getattr(m, attr)
                if val is not None and (math.isinf(val) or math.isnan(val)):
                    setattr(m, attr, 0.0)
            for note in m.notes:
                for attr in ['mapped_x', 'mapped_y']:
                    val = getattr(note, attr)
                    if val is not None and (math.isinf(val) or math.isnan(val)):
                        setattr(note, attr, 0.0)

        # 5. 좌표 매핑 완료 후 동일 위치 중복 음표 재정제 (불러오기 시 쓰레기 잔재 완벽 제거)
        for m in score.measures:
            self.deduplicate_measure_notes(m)

        if score.root_element is not None:
            m_map = {m.number: {n.id for n in m.notes} for m in score.measures}
            for part in score.root_element.findall("part"):
                for m_elem in part.findall("measure"):
                    try:
                        mn = int(m_elem.get("number", "0"))
                    except ValueError:
                        continue
                    if mn in m_map:
                        valid_ids = m_map[mn]
                        seen_ids = set()
                        for n_elem in list(m_elem.findall("note")):
                            nid = n_elem.get("nf-id")
                            if nid and (nid not in valid_ids or nid in seen_ids):
                                m_elem.remove(n_elem)
                            elif nid:
                                seen_ids.add(nid)

    def _extract_mxl(self, mxl_path: str) -> str:
        """MXL 파일 압축을 임시 해제하여 첫번째 xml 파일 경로를 반환합니다."""
        extract_dir = os.path.join(os.path.dirname(mxl_path), "_temp_mxl")
        os.makedirs(extract_dir, exist_ok=True)
        with zipfile.ZipFile(mxl_path, 'r') as zip_ref:
            zip_ref.extractall(extract_dir)
            for f in zip_ref.namelist():
                if f.endswith('.xml') and not f.startswith('META-INF'):
                    return os.path.join(extract_dir, f)
        raise FileNotFoundError("MXL 파일 내에 올바른 XML 악보 데이터가 없습니다.")
