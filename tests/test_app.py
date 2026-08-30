import unittest
import os
import xml.etree.ElementTree as ET
import numpy as np

from core.pdf_renderer import PDFRenderer
from core.musicxml_parser import MusicXMLParser, ParsedScore
from utils.layout_detector import SheetLayoutDetector
from core.auto_aligner import AutoAligner
from core.musicxml_exporter import MusicXMLExporter

class TestSheetSyncStudio(unittest.TestCase):
    def setUp(self):
        self.test_dir = os.path.dirname(os.path.abspath(__file__))
        self.sample_xml_path = os.path.join(self.test_dir, "sample.xml")

        # 생성된 테스트용 샘플 MusicXML 파일
        root = ET.Element("score-partwise")
        part = ET.SubElement(root, "part", id="P1")
        
        # Measure 1
        m1 = ET.SubElement(part, "measure", number="1", width="200.0")
        attr = ET.SubElement(m1, "attributes")
        divs = ET.SubElement(attr, "divisions")
        divs.text = "1"
        time_sig = ET.SubElement(attr, "time")
        beats = ET.SubElement(time_sig, "beats")
        beats.text = "4"
        beat_type = ET.SubElement(time_sig, "beat-type")
        beat_type.text = "4"

        n1 = ET.SubElement(m1, "note")
        p1 = ET.SubElement(n1, "pitch")
        ET.SubElement(p1, "step").text = "C"
        ET.SubElement(p1, "octave").text = "4"
        ET.SubElement(n1, "duration").text = "1"

        n2 = ET.SubElement(m1, "note")
        p2 = ET.SubElement(n2, "pitch")
        ET.SubElement(p2, "step").text = "G"
        ET.SubElement(p2, "octave").text = "4"
        ET.SubElement(n2, "duration").text = "1"

        tree = ET.ElementTree(root)
        tree.write(self.sample_xml_path, encoding="utf-8", xml_declaration=True)

    def test_musicxml_parsing(self):
        parser = MusicXMLParser()
        score = parser.parse(self.sample_xml_path)
        self.assertIsNotNone(score)
        self.assertEqual(len(score.measures), 1)
        self.assertEqual(len(score.measures[0].notes), 2)
        self.assertEqual(score.measures[0].notes[0].pitch, "C4")
        self.assertEqual(score.measures[0].notes[1].pitch, "G4")

    def test_page_distribution(self):
        parser = MusicXMLParser()
        score = parser.parse(self.sample_xml_path)
        parser.distribute_measures_across_pages(score, page_count=5)
        self.assertEqual(score.measures[0].mapped_page, 0)
        self.assertEqual(score.measures[0].notes[0].mapped_page, 0)

    def test_undo_redo(self):
        from core.undo_manager import UndoManager, MoveAction
        parser = MusicXMLParser()
        score = parser.parse(self.sample_xml_path)
        note = score.measures[0].notes[0]
        note.mapped_x = 100.0
        note.mapped_y = 200.0

        undo_mgr = UndoManager()
        action = MoveAction(
            action_type="note",
            item_id=note.id,
            measure_num=note.measure_number,
            old_x=100.0, old_y=200.0,
            new_x=150.0, new_y=250.0
        )
        note.mapped_x = 150.0
        note.mapped_y = 250.0
        undo_mgr.push_action(action)

        # Test Undo
        self.assertTrue(undo_mgr.can_undo)
        undo_mgr.undo(score)
        self.assertEqual(note.mapped_x, 100.0)
        self.assertEqual(note.mapped_y, 200.0)

        # Test Redo
        self.assertTrue(undo_mgr.can_redo)
        undo_mgr.redo(score)
        self.assertEqual(note.mapped_x, 150.0)
        self.assertEqual(note.mapped_y, 250.0)

    def test_layout_detector(self):
        detector = SheetLayoutDetector()
        # 600x800 흰색 배경에 검은색 오선지 5줄 생성
        img = np.ones((800, 600, 3), dtype=np.uint8) * 255
        for y in [100, 110, 120, 130, 140]:
            img[y, 50:550] = [0, 0, 0]
        # 세로 마디선 2개 생성
        img[100:140, 50] = [0, 0, 0]
        img[100:140, 550] = [0, 0, 0]

        systems = detector.detect_staff_lines_and_systems(img)
        self.assertTrue(len(systems) >= 1)
        
        measures = detector.detect_barlines_and_measures(img, systems)
        self.assertTrue(len(measures) >= 1)

    def test_exporter(self):
        parser = MusicXMLParser()
        score = parser.parse(self.sample_xml_path)
        
        # 맵핑 좌표 가상 주입
        score.measures[0].bbox_x1 = 50.0
        score.measures[0].bbox_y1 = 100.0
        score.measures[0].bbox_x2 = 550.0
        score.measures[0].bbox_y2 = 140.0
        score.measures[0].notes[0].mapped_x = 100.0
        score.measures[0].notes[0].mapped_y = 120.0

        exporter = MusicXMLExporter()
        out_xml = os.path.join(self.test_dir, "out.musicxml")
        out_json = os.path.join(self.test_dir, "out.json")

        exporter.export_musicxml(score, out_xml)
        exporter.export_sync_json(score, out_json)

        self.assertTrue(os.path.exists(out_xml))
        self.assertTrue(os.path.exists(out_json))

        # 정리
        if os.path.exists(out_xml): os.remove(out_xml)
        if os.path.exists(out_json): os.remove(out_json)

    def test_precision_calculator(self):
        from core.precision_calculator import PrecisionCalculator
        parser = MusicXMLParser()
        score = parser.parse(self.sample_xml_path)

        # 마디 및 음표 가상 좌표 설정 (Top Line = 100, spacing = 10)
        # F5 = 100, E5 = 105, D5 = 110, C5 = 115, B4 = 120, A4 = 125, G4 = 130, F4 = 135, E4 = 140, D4 = 145, C4 = 150
        score.measures[0].mapped_page = 0
        score.measures[0].bbox_x1 = 100.0
        score.measures[0].bbox_y1 = 80.0
        score.measures[0].bbox_x2 = 500.0
        score.measures[0].bbox_y2 = 250.0

        # Note 1: Y=155 (C4 / Middle C), X=150 (Beat ~0.0)
        score.measures[0].notes[0].mapped_page = 0
        score.measures[0].notes[0].mapped_x = 150.0
        score.measures[0].notes[0].mapped_y = 155.0

        # Note 2: Y=135 (G4 / Sol), X=300 (Beat ~2.0)
        score.measures[0].notes[1].mapped_page = 0
        score.measures[0].notes[1].mapped_x = 300.0
        score.measures[0].notes[1].mapped_y = 135.0

        pdf_renderer = PDFRenderer()
        layout_detector = SheetLayoutDetector()
        calculator = PrecisionCalculator(pdf_renderer, layout_detector)

        stats = calculator.recalculate_score(score, dpi=200, snap_notehead_pixels=False)
        self.assertEqual(stats["status"], "success")
        self.assertEqual(stats["measures_count"], 1)
        self.assertEqual(stats["notes_count"], 2)

        # Verify pitch calculation
        self.assertEqual(score.measures[0].notes[0].pitch, "C4")
        self.assertEqual(score.measures[0].notes[0].staff, 1)
        self.assertEqual(score.measures[0].notes[1].pitch, "G4")
        self.assertEqual(score.measures[0].notes[1].staff, 1)

        # Verify beat and duration calculation
        self.assertAlmostEqual(score.measures[0].notes[0].beat_position, 0.0, delta=0.2)
        self.assertTrue(score.measures[0].notes[0].duration >= 1)

    def tearDown(self):
        if os.path.exists(self.sample_xml_path):
            os.remove(self.sample_xml_path)

if __name__ == "__main__":
    unittest.main()
