import xml.etree.ElementTree as ET
import json
import os
from typing import Optional, Dict, Any
from core.musicxml_parser import ParsedScore

class MusicXMLExporter:
    def __init__(self):
        pass

    def export_musicxml(self, score: ParsedScore, output_path: str):
        """
        보정된 마디 width 및 음표 default-x, default-y 좌표를 주입하여 새로운 MusicXML 파일로 저장합니다.
        """
        if score.xml_tree is None or score.root_element is None:
            raise ValueError("수정할 XML 트리가 파싱되어 있지 않습니다.")

        tree = score.xml_tree
        root = score.root_element

        # 마디 맵핑 룩업 파서
        measure_map = {m.number: m for m in score.measures}

        for part in root.findall("part"):
            # 현재 part가 지원하는 모든 staff (단) 종류를 전체에서 수집 (빈 마디에 추가된 음표 유실 방지)
            all_part_staves = {int(n.findtext("staff", "1")) for n in part.findall("measure/note")}
            if not all_part_staves:
                all_part_staves = {1, 2}

            existing_m_nums = set()
            for m_elem in part.findall("measure"):
                m_num_str = m_elem.get("number", "0")
                try:
                    m_num = int(m_num_str)
                except ValueError:
                    continue
                
                existing_m_nums.add(m_num)

                if m_num in measure_map:
                    m_data = measure_map[m_num]
                    
                    # 마디 width 보정 및 커스텀 메타데이터 주입
                    if m_data.bbox_x1 is not None and m_data.bbox_x2 is not None:
                        calc_w = abs(m_data.bbox_x2 - m_data.bbox_x1) * (72.0 / 200.0)
                        m_elem.set("width", f"{calc_w:.2f}")
                        
                    m_elem.set("nf-page", str(m_data.mapped_page))
                    if m_data.bbox_x1 is not None:
                        m_elem.set("nf-bbox-x1", f"{m_data.bbox_x1:.2f}")
                    if m_data.bbox_y1 is not None:
                        m_elem.set("nf-bbox-y1", f"{m_data.bbox_y1:.2f}")
                    if m_data.bbox_x2 is not None:
                        m_elem.set("nf-bbox-x2", f"{m_data.bbox_x2:.2f}")
                    if m_data.bbox_y2 is not None:
                        m_elem.set("nf-bbox-y2", f"{m_data.bbox_y2:.2f}")

                    # 음표 default-x, default-y 보정 및 커스텀 메타데이터 주입
                    note_nodes = m_elem.findall("note")
                    
                    # 1. 기존 XML 노드 업데이트 및 화면에서 삭제된 노드 제거
                    for idx, n_elem in enumerate(note_nodes):
                        n_id = n_elem.get("nf-id")
                        matching_note = None
                        if n_id:
                            matching_note = next((n for n in m_data.notes if n.id == n_id), None)
                        elif idx < len(m_data.notes):
                            matching_note = m_data.notes[idx]
                            n_elem.set("nf-id", matching_note.id)
                        
                        if matching_note:
                            if matching_note.mapped_x is not None:
                                # default-x는 마디 시작 x1 기준 상대 오프셋
                                rel_x = (matching_note.mapped_x - (m_data.bbox_x1 or 0)) * (72.0 / 200.0)
                                rel_y = (matching_note.mapped_y - (m_data.bbox_y1 or 0)) * (72.0 / 200.0)
                                n_elem.set("default-x", f"{rel_x:.2f}")
                                n_elem.set("default-y", f"{rel_y:.2f}")
                                
                                n_elem.set("nf-mapped-x", f"{matching_note.mapped_x:.2f}")
                                n_elem.set("nf-mapped-y", f"{matching_note.mapped_y:.2f}")
                                n_elem.set("nf-page", str(matching_note.mapped_page))
                            
                            # staff 속성 갱신
                            staff_elem = n_elem.find("staff")
                            if staff_elem is not None:
                                staff_elem.text = str(matching_note.staff)
                        else:
                            # 사용자가 화면에서 삭제한 음표는 XML에서도 삭제하여 완벽 덮어쓰기 적용
                            m_elem.remove(n_elem)
                    
                    # 2. 화면에서 새로 추가되거나 복제된 음표를 XML에 신규 삽입
                    existing_ids = {n_elem.get("nf-id") for n_elem in m_elem.findall("note") if n_elem.get("nf-id")}
                    for n_data in m_data.notes:
                        if n_data.id not in existing_ids and n_data.staff in all_part_staves:
                            # barline 태그가 존재할 경우 그 앞에 추가하여 XML 구조 오류 방지
                            insert_idx = len(m_elem)
                            for i, child in enumerate(m_elem):
                                if child.tag == 'barline':
                                    insert_idx = i
                                    break
                            
                            new_elem = ET.Element("note")
                            m_elem.insert(insert_idx, new_elem)
                            new_elem.set("nf-id", n_data.id)
                            
                            if n_data.is_rest:
                                ET.SubElement(new_elem, "rest")
                            else:
                                pitch_elem = ET.SubElement(new_elem, "pitch")
                                step = ET.SubElement(pitch_elem, "step")
                                step.text = n_data.pitch[0].upper() if n_data.pitch else "C"
                                if len(n_data.pitch) > 1 and n_data.pitch[1] in ['#', 'b']:
                                    alter = ET.SubElement(pitch_elem, "alter")
                                    alter.text = "1" if n_data.pitch[1] == '#' else "-1"
                                oct_elem = ET.SubElement(pitch_elem, "octave")
                                oct_elem.text = n_data.pitch[-1] if n_data.pitch[-1].isdigit() else "4"
                            
                            dur = ET.SubElement(new_elem, "duration")
                            dur.text = str(n_data.duration)
                            voice = ET.SubElement(new_elem, "voice")
                            voice.text = str(n_data.voice)
                            staff = ET.SubElement(new_elem, "staff")
                            staff.text = str(n_data.staff)

                            if n_data.mapped_x is not None:
                                rel_x = (n_data.mapped_x - (m_data.bbox_x1 or 0)) * (72.0 / 200.0)
                                rel_y = (n_data.mapped_y - (m_data.bbox_y1 or 0)) * (72.0 / 200.0)
                                new_elem.set("default-x", f"{rel_x:.2f}")
                                new_elem.set("default-y", f"{rel_y:.2f}")
                                new_elem.set("nf-mapped-x", f"{n_data.mapped_x:.2f}")
                                new_elem.set("nf-mapped-y", f"{n_data.mapped_y:.2f}")
                                new_elem.set("nf-page", str(n_data.mapped_page))

            # 3. 비어 있는 세로 마디 영역이 새로 추가된 경우 (XML에 없는 마디) 삽입 처리
            for m_data in score.measures:
                if m_data.number not in existing_m_nums:
                    # 번호 순서에 맞게 삽입할 위치 탐색
                    insert_idx = len(part)
                    for i, child in enumerate(part):
                        if child.tag == "measure":
                            try:
                                child_num = int(child.get("number", "0"))
                                if child_num > m_data.number:
                                    insert_idx = i
                                    break
                            except ValueError:
                                pass
                                
                    new_m_elem = ET.Element("measure")
                    new_m_elem.set("number", str(m_data.number))
                    part.insert(insert_idx, new_m_elem)
                    
                    if m_data.bbox_x1 is not None and m_data.bbox_x2 is not None:
                        calc_w = abs(m_data.bbox_x2 - m_data.bbox_x1) * (72.0 / 200.0)
                        new_m_elem.set("width", f"{calc_w:.2f}")
                    new_m_elem.set("nf-page", str(m_data.mapped_page))
                    if m_data.bbox_x1 is not None:
                        new_m_elem.set("nf-bbox-x1", f"{m_data.bbox_x1:.2f}")
                    if m_data.bbox_y1 is not None:
                        new_m_elem.set("nf-bbox-y1", f"{m_data.bbox_y1:.2f}")
                    if m_data.bbox_x2 is not None:
                        new_m_elem.set("nf-bbox-x2", f"{m_data.bbox_x2:.2f}")
                    if m_data.bbox_y2 is not None:
                        new_m_elem.set("nf-bbox-y2", f"{m_data.bbox_y2:.2f}")
                    
                    # 새 마디에 속한 음표들 추가
                    for n_data in m_data.notes:
                        if n_data.staff in all_part_staves:
                            new_elem = ET.SubElement(new_m_elem, "note")
                            new_elem.set("nf-id", n_data.id)
                            if n_data.is_rest:
                                ET.SubElement(new_elem, "rest")
                            else:
                                pitch_elem = ET.SubElement(new_elem, "pitch")
                                step = ET.SubElement(pitch_elem, "step")
                                step.text = n_data.pitch[0].upper() if n_data.pitch else "C"
                                if len(n_data.pitch) > 1 and n_data.pitch[1] in ['#', 'b']:
                                    alter = ET.SubElement(pitch_elem, "alter")
                                    alter.text = "1" if n_data.pitch[1] == '#' else "-1"
                                oct_elem = ET.SubElement(pitch_elem, "octave")
                                oct_elem.text = n_data.pitch[-1] if n_data.pitch[-1].isdigit() else "4"
                            
                            dur = ET.SubElement(new_elem, "duration")
                            dur.text = str(n_data.duration)
                            voice = ET.SubElement(new_elem, "voice")
                            voice.text = str(n_data.voice)
                            staff = ET.SubElement(new_elem, "staff")
                            staff.text = str(n_data.staff)

                            if n_data.mapped_x is not None:
                                rel_x = (n_data.mapped_x - (m_data.bbox_x1 or 0)) * (72.0 / 200.0)
                                rel_y = (n_data.mapped_y - (m_data.bbox_y1 or 0)) * (72.0 / 200.0)
                                new_elem.set("default-x", f"{rel_x:.2f}")
                                new_elem.set("default-y", f"{rel_y:.2f}")
                                new_elem.set("nf-mapped-x", f"{n_data.mapped_x:.2f}")
                                new_elem.set("nf-mapped-y", f"{n_data.mapped_y:.2f}")
                                new_elem.set("nf-page", str(n_data.mapped_page))

        # XML 인덴트 및 저장
        ET.indent(tree, space="  ", level=0)
        tree.write(output_path, encoding="utf-8", xml_declaration=True)

    def export_sync_json(self, score: ParsedScore, json_path: str):
        """
        NoteFlow Studio 비디오 생성 엔진에서 즉시 로드할 수 있는 싱크 JSON 데이터를 생성합니다.
        """
        export_data: Dict[str, Any] = {
            "title": score.title,
            "composer": score.composer,
            "total_measures": score.total_measures,
            "measures": []
        }

        for m in score.measures:
            m_info = {
                "number": m.number,
                "page": m.mapped_page,
                "time_signature": m.time_signature,
                "bbox": {
                    "x1": m.bbox_x1,
                    "y1": m.bbox_y1,
                    "x2": m.bbox_x2,
                    "y2": m.bbox_y2
                },
                "notes": []
            }
            for n in m.notes:
                n_info = {
                    "id": n.id,
                    "pitch": n.pitch,
                    "is_rest": n.is_rest,
                    "beat_position": n.beat_position,
                    "page": n.mapped_page,
                    "x": n.mapped_x,
                    "y": n.mapped_y
                }
                m_info["notes"].append(n_info)
            export_data["measures"].append(m_info)

        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, ensure_ascii=False, indent=2)

    def export_project_session(self, score: ParsedScore, pdf_path: str, xml_path: str, current_page: int, session_path: str):
        """
        현재 작업 세션(PDF 경로, MusicXML 경로, 현재 페이지 및 보정된 모든 마디/음표 2D 좌표)을 세션 파일(.nfsp / .json)로 저장합니다.
        """
        session_data = {
            "version": "1.0",
            "pdf_path": pdf_path,
            "xml_path": xml_path,
            "current_page": current_page,
            "score": {
                "title": score.title,
                "composer": score.composer,
                "total_measures": score.total_measures,
                "measures": []
            }
        }

        for m in score.measures:
            m_info = {
                "number": m.number,
                "page": m.mapped_page,
                "time_signature": m.time_signature,
                "bbox": {"x1": m.bbox_x1, "y1": m.bbox_y1, "x2": m.bbox_x2, "y2": m.bbox_y2},
                "notes": []
            }
            for n in m.notes:
                n_info = {
                    "id": n.id,
                    "pitch": n.pitch,
                    "is_rest": n.is_rest,
                    "beat_position": n.beat_position,
                    "voice": n.voice,
                    "staff": n.staff,
                    "page": n.mapped_page,
                    "x": n.mapped_x,
                    "y": n.mapped_y
                }
                m_info["notes"].append(n_info)
            session_data["score"]["measures"].append(m_info)

        with open(session_path, 'w', encoding='utf-8') as f:
            json.dump(session_data, f, ensure_ascii=False, indent=2)

    def load_project_session(self, session_path: str) -> Dict[str, Any]:
        """
        저장된 세션 프로젝트 파일(.nfsp / .json)을 로드하여 이전 작업 상태를 복원합니다.
        """
        with open(session_path, 'r', encoding='utf-8') as f:
            return json.load(f)
