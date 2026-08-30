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

                # 원본 XML의 불필요한 쓰레기 데이터(레이아웃, 재생, 지시어 등) 원천 필터링
                for garbage_tag in ["print", "direction", "sound", "harmony", "grouping", "figure"]:
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
        """PDF 총 페이지 수에 맞춰 MusicXML 마디 및 음표를 각 페이지별로 균등 배치 및 초기 좌표 생성합니다."""
        if not score or not score.measures or page_count <= 0:
            return

        # 1. new-page 태그가 있는지 확인
        has_new_page_tags = any(m.new_page for m in score.measures)
        # 2. 이미 XML 속성(nf-bbox-x1 등)으로 커스텀 맵핑 좌표가 로드되어 있는지 확인
        has_custom_mapping = any(m.bbox_x1 is not None for m in score.measures)
        
        current_page = 0
        total_m = len(score.measures)
        measures_per_page = max(1, (total_m + page_count - 1) // page_count) if not has_new_page_tags else 0

        for idx, m in enumerate(score.measures):
            # 커스텀 맵핑(nf-page, nf-bbox-x1)이 이미 존재하는 경우 해당 페이지 보존
            if has_custom_mapping and m.bbox_x1 is not None:
                m.mapped_page = min(page_count - 1, max(0, m.mapped_page))
            elif has_new_page_tags:
                if m.new_page and idx > 0:
                    current_page = min(page_count - 1, current_page + 1)
                m.mapped_page = current_page
            else:
                m.mapped_page = min(page_count - 1, idx // measures_per_page)

            # 초기 임시 좌표 할당 (auto_aligner 실행 전에도 오버레이 표시되도록)
            page_m_idx = idx % max(1, measures_per_page)
            pw, ph = 1200.0, 1600.0
            if pdf_renderer and pdf_renderer.doc:
                w, h = pdf_renderer.get_page_size(m.mapped_page)
                scale = dpi / 72.0
                pw, ph = w * scale, h * scale

            row = (page_m_idx // 4) % 6
            col = page_m_idx % 4

            box_x1 = pw * 0.08 + col * (pw * 0.22)
            box_x2 = box_x1 + pw * 0.20
            box_y1 = ph * 0.12 + row * (ph * 0.13)
            box_y2 = box_y1 + ph * 0.11

            # 이미 MusicXML(nf-bbox-x1 등)에서 절대 좌표를 성공적으로 불러왔다면, 임시 그리드로 덮어쓰지 않음!
            if m.bbox_x1 is None:
                m.bbox_x1, m.bbox_y1 = box_x1, box_y1
                m.bbox_x2, m.bbox_y2 = box_x2, box_y2
            else:
                # 기존 좌표 유지 및 아래 음표 오프셋 연산용으로 업데이트
                box_x1, box_y1 = m.bbox_x1, m.bbox_y1
                box_x2 = m.bbox_x2 if m.bbox_x2 is not None else box_x1 + pw * 0.20

            for n_idx, note in enumerate(m.notes):
                note.mapped_page = m.mapped_page
                
                # 이미 유효한 음표 절대 좌표(nf-mapped-x)가 존재한다면 덮어쓰지 않음!
                if note.mapped_x is not None and note.mapped_y is not None:
                    continue
                    
                scale = dpi / 72.0
                if note.default_x is not None:
                    note.mapped_x = box_x1 + (note.default_x * scale)
                else:
                    note.mapped_x = box_x1 + ((n_idx + 0.5) / max(1, len(m.notes))) * (box_x2 - box_x1)

                if note.default_y is not None:
                    note.mapped_y = box_y1 + (note.default_y * scale)
                else:
                    note.mapped_y = (box_y1 + box_y2) / 2.0

            import math
            for attr in ['bbox_x1', 'bbox_y1', 'bbox_x2', 'bbox_y2']:
                val = getattr(m, attr)
                if val is not None and (math.isinf(val) or math.isnan(val)):
                    setattr(m, attr, 0.0)
            for note in m.notes:
                for attr in ['mapped_x', 'mapped_y']:
                    val = getattr(note, attr)
                    if val is not None and (math.isinf(val) or math.isnan(val)):
                        setattr(note, attr, 0.0)

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
