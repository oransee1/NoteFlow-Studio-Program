import os
import sys
import uuid
from typing import Optional, Any, List, Dict, Tuple
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QFileDialog, QMessageBox,
    QStatusBar, QToolBar, QSplitter, QFrame, QLabel, QPushButton
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon, QAction

from core.pdf_renderer import PDFRenderer
from core.musicxml_parser import MusicXMLParser, ParsedScore, MeasureData, NoteData
from utils.layout_detector import SheetLayoutDetector
from core.auto_aligner import AutoAligner, detect_pitch_from_y
from core.musicxml_exporter import MusicXMLExporter
from core.undo_manager import UndoManager, EditAction, GroupAction
from ui.graphics_view import ScoreGraphicsView, InteractiveNoteItem, InteractiveMeasureItem
from ui.control_panel import ControlPanel

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("NoteFlow Sheet Sync Studio - 악보 싱크 및 맵핑 오버레이 툴")
        self.resize(1280, 850)

        # Core logic engines
        self.pdf_renderer = PDFRenderer()
        self.xml_parser = MusicXMLParser()
        self.layout_detector = SheetLayoutDetector()
        self.auto_aligner = AutoAligner(self.pdf_renderer, self.layout_detector)
        self.xml_exporter = MusicXMLExporter()
        self.undo_manager = UndoManager()

        # State
        self.score: Optional[ParsedScore] = None
        self.current_page_idx: int = 0
        self.pdf_loaded: bool = False
        self.xml_loaded: bool = False

        self.init_ui()

    def init_ui(self):
        # Central widget & layout
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)

        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 수평 스플리터 (캔버스 좌측, 제어 패널 우측)
        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        main_layout.addWidget(splitter)

        # 캔버스 메인 영역 래퍼 (상단 범례 표시 바 + 캔버스 뷰)
        canvas_container = QWidget(self)
        canvas_layout = QVBoxLayout(canvas_container)
        canvas_layout.setContentsMargins(0, 0, 0, 0)
        canvas_layout.setSpacing(0)

        # 상단 음표 파트 색상 범례 Bar
        legend_bar = QFrame()
        legend_bar.setStyleSheet("""
            QFrame {
                background-color: #F8FAFC;
                border-bottom: 1px solid #E2E8F0;
                padding: 4px 10px;
            }
        """)
        lg_layout = QHBoxLayout(legend_bar)
        lg_layout.setContentsMargins(10, 4, 10, 4)
        lg_layout.setSpacing(12)

        title_lbl = QLabel("🎨 파트 색상 범례:")
        title_lbl.setStyleSheet("font-weight: bold; color: #334155; font-size: 12px;")

        badge_treble = QLabel("🟢 높은음자리표 (오른손 / 녹색)")
        badge_treble.setStyleSheet("""
            QLabel {
                background-color: #DCFCE7; color: #15803D; font-weight: bold; font-size: 11px;
                padding: 3px 8px; border-radius: 12px; border: 1px solid #86EFAC;
            }
        """)

        badge_bass = QLabel("🔵 낮은음자리표 (왼손 / 파란색)")
        badge_bass.setStyleSheet("""
            QLabel {
                background-color: #E0F2FE; color: #0369A1; font-weight: bold; font-size: 11px;
                padding: 3px 8px; border-radius: 12px; border: 1px solid #7DD3FC;
            }
        """)

        badge_rest = QLabel("🟡 쉼표 (Rest / 노란색)")
        badge_rest.setStyleSheet("""
            QLabel {
                background-color: #FEF9C3; color: #A16207; font-weight: bold; font-size: 11px;
                padding: 3px 8px; border-radius: 12px; border: 1px solid #FDE047;
            }
        """)

        # 마퀴 선택 모드 토글 버튼
        self.btn_mode_toggle = QPushButton("🔲 마퀴 드래그 선택 모드")
        self.btn_mode_toggle.setCheckable(True)
        self.btn_mode_toggle.setChecked(True)
        self.btn_mode_toggle.setStyleSheet("""
            QPushButton {
                background-color: #0EA5E9; color: white; font-weight: bold; font-size: 11px;
                padding: 4px 10px; border-radius: 6px; border: none;
            }
            QPushButton:hover { background-color: #0284C7; }
            QPushButton:unchecked {
                background-color: #475569; color: white;
            }
        """)
        self.btn_mode_toggle.toggled.connect(self._on_mode_toggled)

        tip_lbl = QLabel("💡 팁: Shift+드래그: 수평 고정 이동 (음높이 Y보존) / Space+드래그: 화면 이동")
        tip_lbl.setStyleSheet("color: #64748B; font-size: 11px; font-style: italic;")

        lg_layout.addWidget(title_lbl)
        lg_layout.addWidget(badge_treble)
        lg_layout.addWidget(badge_bass)
        lg_layout.addWidget(badge_rest)
        lg_layout.addWidget(self.btn_mode_toggle)
        lg_layout.addStretch()
        lg_layout.addWidget(tip_lbl)

        canvas_layout.addWidget(legend_bar)

        # 캔버스 뷰
        self.canvas_view = ScoreGraphicsView(self)
        self.canvas_view.position_changed.connect(self._update_coords_status)
        self.canvas_view.action_recorded_signal.connect(self._on_action_recorded)
        canvas_layout.addWidget(self.canvas_view)

        splitter.addWidget(canvas_container)

        # 컨트롤 사이드바
        self.control_panel = ControlPanel(self)
        splitter.addWidget(self.control_panel)

        # 비율 설정 (캔버스 : 사이드바 = 4 : 1)
        splitter.setSizes([950, 300])

        # 시그널 연결
        self.control_panel.open_pdf_signal.connect(self.load_pdf_dialog)
        self.control_panel.open_xml_signal.connect(self.load_xml_dialog)
        self.control_panel.auto_sync_signal.connect(self.run_auto_sync)
        self.control_panel.save_project_signal.connect(self.save_project_dialog)
        self.control_panel.load_project_signal.connect(self.load_project_dialog)
        self.control_panel.save_xml_signal.connect(self.save_xml_dialog)
        self.control_panel.save_json_signal.connect(self.save_json_dialog)
        self.control_panel.page_changed_signal.connect(self.change_page)
        self.control_panel.visibility_toggled_signal.connect(self.update_overlay_visibility)
        self.control_panel.offset_applied_signal.connect(self.apply_page_offset)
        self.control_panel.measure_resized_signal.connect(self.apply_measure_resize)
        self.control_panel.refresh_measure_nums_signal.connect(self.refresh_measure_numbers)

        self.canvas_view.add_note_at_signal.connect(self.create_note_at)
        self.canvas_view.add_measure_at_signal.connect(self.create_measure_at)
        self.canvas_view.delete_selected_signal.connect(self.delete_selected)
        self.canvas_view.duplicate_note_signal.connect(self.duplicate_note)
        self.canvas_view.align_measure_notes_signal.connect(self.auto_align_single_measure)
        self.canvas_view.delete_measure_signal.connect(self.delete_measure)
        self.canvas_view.delete_single_note_signal.connect(self.delete_single_note)

        # 메뉴 바 및 단축키 바인딩 생성
        self.create_menu_bar()

        # 상태 바
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("준비 완료 - PDF 및 MusicXML 파일을 불러오세요.")

        # Drag and Drop 활성화
        self.setAcceptDrops(True)

    def create_menu_bar(self):
        """Windows 표준 메뉴 바 및 단축키 설정"""
        menubar = self.menuBar()

        # 1. 파일 (File) 메뉴
        file_menu = menubar.addMenu("파일(&F)")

        open_pdf_act = QAction("📄 PDF 악보 열기...", self)
        open_pdf_act.setShortcut("Ctrl+O")
        open_pdf_act.triggered.connect(self.load_pdf_dialog)

        open_xml_act = QAction("🎼 MusicXML 열기...", self)
        open_xml_act.setShortcut("Ctrl+Shift+O")
        open_xml_act.triggered.connect(self.load_xml_dialog)

        save_proj_act = QAction("💾 프로젝트 세션 저장...", self)
        save_proj_act.setShortcut("Ctrl+Shift+P")
        save_proj_act.triggered.connect(self.save_project_dialog)

        load_proj_act = QAction("📂 프로젝트 세션 불러오기...", self)
        load_proj_act.setShortcut("Ctrl+Shift+L")
        load_proj_act.triggered.connect(self.load_project_dialog)

        save_xml_act = QAction("🎼 완성된 MusicXML 저장...", self)
        save_xml_act.setShortcut("Ctrl+S")
        save_xml_act.triggered.connect(self.save_xml_dialog)

        save_json_act = QAction("🎬 비디오 싱크 JSON 저장...", self)
        save_json_act.setShortcut("Ctrl+Shift+S")
        save_json_act.triggered.connect(self.save_json_dialog)

        exit_act = QAction("종료(&X)", self)
        exit_act.setShortcut("Alt+F4")
        exit_act.triggered.connect(self.close)

        file_menu.addAction(open_pdf_act)
        file_menu.addAction(open_xml_act)
        file_menu.addSeparator()
        file_menu.addAction(save_proj_act)
        file_menu.addAction(load_proj_act)
        file_menu.addSeparator()
        file_menu.addAction(save_xml_act)
        file_menu.addAction(save_json_act)
        file_menu.addSeparator()
        file_menu.addAction(exit_act)

        # 2. 편집 (Edit) 메뉴 - Undo / Redo
        edit_menu = menubar.addMenu("편집(&E)")

        undo_act = QAction("↩️ 이전으로 돌아가기 (Undo)", self)
        undo_act.setShortcut("Ctrl+Z")
        undo_act.triggered.connect(self.perform_undo)

        redo_act = QAction("↪️ 다시 실행 (Redo)", self)
        redo_act.setShortcut("Ctrl+Y")
        redo_act.triggered.connect(self.perform_redo)

        edit_menu.addAction(undo_act)
        edit_menu.addAction(redo_act)

        # 3. 보기 (View) 메뉴
        view_menu = menubar.addMenu("보기(&V)")

        zoom_in_act = QAction("화면 확대", self)
        zoom_in_act.setShortcut("Ctrl+=")
        zoom_in_act.triggered.connect(self.canvas_view.zoom_in)

        zoom_out_act = QAction("화면 축소", self)
        zoom_out_act.setShortcut("Ctrl+-")
        zoom_out_act.triggered.connect(self.canvas_view.zoom_out)

        zoom_fit_act = QAction("화면에 맞추기", self)
        zoom_fit_act.setShortcut("Ctrl+0")
        zoom_fit_act.triggered.connect(self.canvas_view.zoom_fit_page)

        toggle_measures_act = QAction("마디 구분 영역 표시 토글", self)
        toggle_measures_act.setShortcut("Ctrl+M")
        toggle_measures_act.triggered.connect(self._toggle_measures)

        toggle_notes_act = QAction("음표 위치 점 표시 토글", self)
        toggle_notes_act.setShortcut("Ctrl+N")
        toggle_notes_act.triggered.connect(self._toggle_notes)

        view_menu.addAction(zoom_in_act)
        view_menu.addAction(zoom_out_act)
        view_menu.addAction(zoom_fit_act)
        view_menu.addSeparator()
        view_menu.addAction(toggle_measures_act)
        view_menu.addAction(toggle_notes_act)

        # 3. 이동 (Navigate) 메뉴
        nav_menu = menubar.addMenu("이동(&N)")

        first_page_act = QAction("첫 페이지로 이동", self)
        first_page_act.setShortcut("Home")
        first_page_act.triggered.connect(lambda: self.change_page(0))

        prev_page_act = QAction("이전 페이지", self)
        prev_page_act.setShortcut("Left")
        prev_page_act.triggered.connect(lambda: self.change_page(max(0, self.current_page_idx - 1)))

        next_page_act = QAction("다음 페이지", self)
        next_page_act.setShortcut("Right")
        next_page_act.triggered.connect(lambda: self.change_page(min(max(0, self.pdf_renderer.page_count - 1), self.current_page_idx + 1)))

        last_page_act = QAction("마지막 페이지로 이동", self)
        last_page_act.setShortcut("End")
        last_page_act.triggered.connect(lambda: self.change_page(max(0, self.pdf_renderer.page_count - 1)))

        nav_menu.addAction(first_page_act)
        nav_menu.addAction(prev_page_act)
        nav_menu.addAction(next_page_act)
        nav_menu.addAction(last_page_act)

        # 4. 도구 (Tools) 메뉴
        tools_menu = menubar.addMenu("도구(&T)")

        sync_act = QAction("✨ 자동 싱크 맞추기", self)
        sync_act.setShortcut("F5")
        sync_act.triggered.connect(self.run_auto_sync)
        tools_menu.addAction(sync_act)

        # 5. 도움말 (Help) 메뉴
        help_menu = menubar.addMenu("도움말(&H)")
        help_act = QAction("단축키 안내(&K)...", self)
        help_act.setShortcut("F1")
        help_act.triggered.connect(self.show_help_dialog)
        help_menu.addAction(help_act)

    def _on_mode_toggled(self, checked: bool):
        if checked:
            self.canvas_view.set_marquee_mode(True)
            self.btn_mode_toggle.setText("🔲 마퀴 드래그 선택 모드")
            self.status_bar.showMessage("🔲 마퀴 다중 선택 모드 활성화: 대각선 드래그로 영역 내 음표들을 한번에 다중 선택하세요 (Space+드래그: 화면 이동).")
        else:
            self.canvas_view.set_marquee_mode(False)
            self.btn_mode_toggle.setText("🖐️ 캔버스 손바닥 이동 모드")
            self.status_bar.showMessage("🖐️ 캔버스 이동 모드 활성화: 드래그하여 악보 캔버스를 자유롭게 이동하세요.")

    def perform_undo(self):
        """Ctrl+Z 이전 단일 작업만 취소 되돌리기"""
        if not self.score:
            return
        action = self.undo_manager.undo(self.score)
        if action:
            self.render_current_page()
            desc = getattr(action, 'description', '이전 작업')
            self.status_bar.showMessage(f"↩️ 이전으로 돌아가기 (Undo 완료): {desc}")

    def perform_redo(self):
        """Ctrl+Y 되돌린 단일 작업 다시 실행"""
        if not self.score:
            return
        action = self.undo_manager.redo(self.score)
        if action:
            self.render_current_page()
            desc = getattr(action, 'description', '다시 실행')
            self.status_bar.showMessage(f"↪️ 다시 실행 (Redo 완료): {desc}")

    def _toggle_measures(self):
        chk = not self.control_panel.chk_measures.isChecked()
        self.control_panel.chk_measures.setChecked(chk)

    def _toggle_notes(self):
        chk = not self.control_panel.chk_notes.isChecked()
        self.control_panel.chk_notes.setChecked(chk)

    def show_help_dialog(self):
        help_text = """
<h3>⌨️ NoteFlow Sheet Sync Studio 단축키 안내</h3>
<table border="1" cellspacing="0" cellpadding="5" style="border-collapse: collapse; width: 100%;">
  <tr style="background-color: #F1F5F9;"><th>기능</th><th>Windows 단축키</th></tr>
  <tr><td>PDF 악보 열기</td><td><b>Ctrl + O</b></td></tr>
  <tr><td>MusicXML 열기</td><td><b>Ctrl + Shift + O</b></td></tr>
  <tr><td>완성된 MusicXML 저장</td><td><b>Ctrl + S</b></td></tr>
  <tr><td>비디오 싱크 JSON 저장</td><td><b>Ctrl + Shift + S</b></td></tr>
  <tr><td>자동 싱크 맞추기</td><td><b>F5</b> 또는 <b>Ctrl + R</b></td></tr>
  <tr><td>이전 / 다음 페이지</td><td><b>← / →</b> 또는 <b>PageUp / PageDown</b></td></tr>
  <tr><td>첫 / 마지막 페이지</td><td><b>Home / End</b></td></tr>
  <tr><td>화면 확대 / 축소</td><td><b>Ctrl + + / Ctrl + -</b> (Ctrl+휠)</td></tr>
  <tr><td>화면에 맞추기</td><td><b>Ctrl + 0</b></td></tr>
  <tr><td>마디 영역 토글</td><td><b>Ctrl + M</b></td></tr>
  <tr><td>음표 위치 점 토글</td><td><b>Ctrl + N</b></td></tr>
  <tr><td>단축키 도움말</td><td><b>F1</b></td></tr>
  <tr><td>프로그램 종료</td><td><b>Alt + F4</b> 또는 <b>Ctrl + Q</b></td></tr>
</table>
"""
        QMessageBox.information(self, "단축키 안내", help_text)

    def load_pdf_dialog(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "PDF 악보 파일 열기", "", "PDF Files (*.pdf)"
        )
        if file_path:
            self.load_pdf_file(file_path)

    def load_pdf_file(self, path: str):
        try:
            page_count = self.pdf_renderer.load_pdf(path)
            self.pdf_loaded = True
            self.current_pdf_path = path
            self.current_page_idx = 0
            self.control_panel.lbl_pdf_info.setText(os.path.basename(path))

            if self.score:
                has_custom = any(m.bbox_x1 is not None for m in self.score.measures)
                if not has_custom:
                    self.score = self.auto_aligner.align_score(self.score, dpi=200)
                else:
                    self.xml_parser.distribute_measures_across_pages(
                        self.score, page_count, dpi=200, pdf_renderer=self.pdf_renderer
                    )

            self.control_panel.update_page_info(0, page_count, self.score)
            self.render_current_page()
            self.status_bar.showMessage(f"PDF 로드 완료 ({page_count} 페이지): {path}")
        except Exception as e:
            QMessageBox.critical(self, "오류", f"PDF 파일을 읽는 도중 오류가 발생했습니다:\n{str(e)}")

    def load_xml_dialog(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "MusicXML 파일 열기", "", "MusicXML Files (*.xml *.musicxml *.mxl)"
        )
        if file_path:
            self.load_xml_file(file_path)

    def load_xml_file(self, path: str):
        try:
            self.score = self.xml_parser.parse(path)
            self.xml_loaded = True
            self.current_xml_path = path
            self.control_panel.lbl_xml_info.setText(f"{os.path.basename(path)}\n({self.score.total_measures} 마디)")

            if self.pdf_loaded:
                has_custom = any(m.bbox_x1 is not None for m in self.score.measures)
                if not has_custom:
                    self.score = self.auto_aligner.align_score(self.score, dpi=200)
                else:
                    self.xml_parser.distribute_measures_across_pages(
                        self.score, self.pdf_renderer.page_count, dpi=200, pdf_renderer=self.pdf_renderer
                    )
                self.control_panel.update_page_info(self.current_page_idx, self.pdf_renderer.page_count, self.score)

            self.status_bar.showMessage(f"MusicXML 로드 완료 ({self.score.total_measures} 마디): {self.score.title}")
            
            # PDF가 이미 들어와 있다면 초기 오버레이 렌더링
            if self.pdf_loaded and self.score:
                self.render_current_page()
        except Exception as e:
            QMessageBox.critical(self, "오류", f"MusicXML 파싱 중 오류가 발생했습니다:\n{str(e)}")

    def render_current_page(self):
        if not self.pdf_loaded:
            return

        pixmap, bgr_img, _ = self.pdf_renderer.render_page_pixmap(self.current_page_idx, dpi=200)
        self.canvas_view.set_pdf_pixmap(pixmap)

        # PDF 세로 마디선 자석 스냅 위치 탐지 & 전달
        if bgr_img is not None:
            try:
                systems = self.layout_detector.detect_staff_lines_and_systems(bgr_img)
                self.layout_detector.detect_barlines_and_measures(bgr_img, systems)
                barlines_x = sorted(list(set(float(bx) for sys in systems for bx in sys.barline_xs if bx > 0)))
                self.canvas_view.set_snap_barlines(barlines_x)
            except Exception:
                pass

        if self.score:
            self.canvas_view.display_overlay(self.score.measures, self.current_page_idx)

    def change_page(self, page_index: int):
        self.current_page_idx = page_index
        self.control_panel.update_page_info(page_index, self.pdf_renderer.page_count, self.score)
        self.render_current_page()
        
        m_range_str = ""
        if self.score:
            p_measures = [m.number for m in self.score.measures if m.mapped_page == page_index]
            if p_measures:
                m_range_str = f" (마디 {min(p_measures)} ~ {max(p_measures)})"

        self.status_bar.showMessage(f"동기화 페이지 이동: {page_index + 1} / {self.pdf_renderer.page_count}{m_range_str}")

    def run_auto_sync(self):
        """싱크 맞추기 버튼 클릭 시 동작하는 자동 악보 스캐닝 및 맵핑 알고리즘"""
        if not self.pdf_loaded or not self.xml_loaded or not self.score:
            QMessageBox.warning(self, "경고", "PDF 파일과 MusicXML 파일을 모두 로드해 주세요.")
            return

        self.undo_manager.push_snapshot(self.score, "전체 자동 싱크 맞추기")

        self.status_bar.showMessage("악보 이미지를 스캔하여 음표 및 마디 좌표를 자동으로 매칭 중입니다...")
        self.setCursor(Qt.CursorShape.WaitCursor)

        try:
            self.score = self.auto_aligner.align_score(self.score, dpi=200)
            self.render_current_page()
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self.status_bar.showMessage("✨ 자동 싱크 맵핑 완료! 화면의 오버레이 점 위치를 확인하고 필요시 조정하세요.")
            QMessageBox.information(
                self, "싱크 맵핑 완료",
                "자동 악보 스캐닝 및 MusicXML 음표 맵핑이 완료되었습니다!\n\n"
                "화면에 오버레이된 점과 마디 영역을 눈으로 확인하신 후,\n"
                "드래그하여 미세 수정한 뒤 [완성된 MusicXML 저장] 버튼을 누르세요."
            )
        except Exception as e:
            self.setCursor(Qt.CursorShape.ArrowCursor)
            QMessageBox.critical(self, "오류", f"자동 싱크 연산 중 오류가 발생했습니다:\n{str(e)}")

    def auto_align_single_measure(self, m_data: MeasureData):
        """마디 세로 영역을 맞추고 우클릭 시 해당 마디 내 음표 점들을 높은/낮은/쉼표 오선지에 자동 착 붙이고 미배치 음표를 새로 감지해 채워줍니다."""
        if not self.pdf_loaded or not m_data:
            return

        self.undo_manager.push_snapshot(self.score, f"마디 M{m_data.number} 자동 맞춤")

        self.status_bar.showMessage(f"🎯 마디 M{m_data.number} 음표 자동 맞춤 & 미배치 음표 감지 중...")
        self.setCursor(Qt.CursorShape.WaitCursor)

        try:
            aligned_count, created_count = self.auto_aligner.align_single_measure(m_data, dpi=200)
            self.render_current_page()
            self.setCursor(Qt.CursorShape.ArrowCursor)

            msg = f"✨ 마디 M{m_data.number} 음표 자동 맞춤 완료! (오선지 정렬: {aligned_count}개, 새로 추가 생성: {created_count}개)"
            self.status_bar.showMessage(msg)
            QMessageBox.information(
                self, "마디 음표 자동 맞춤 완료",
                f"마디 M{m_data.number} 영역의 음표 자동 맞춤 및 채우기가 완료되었습니다!\n\n"
                f"• 높은음자리(녹색) / 낮은음자리(파란색) / 쉼표(노란색) 오선지 맞춤: {aligned_count}개\n"
                f"• 누락된 위치에 새로 추가 채운 음표: {created_count}개"
            )
        except Exception as e:
            self.setCursor(Qt.CursorShape.ArrowCursor)
            QMessageBox.critical(self, "오류", f"마디 음표 자동 맞춤 연산 중 오류가 발생했습니다:\n{str(e)}")

    def _on_action_recorded(self, action: Any):
        if self.score:
            # EditAction이므로 score를 전달하지 않고 단일 액션 모드로 푸시 (이전 상태 롤백 100% 지원)
            self.undo_manager.push_action(action)

    def create_measure_at(self, x: float, y: float):
        """빈 공간을 우클릭하여 새로운 마디(세로 마디 영역)를 생성하고, 이후 마디들의 번호를 1씩 자동으로 밀어냅니다."""
        if not self.score: return
        page_idx = self.current_page_idx
        
        self.undo_manager.push_snapshot(self.score, "새 마디 영역 추가")
        
        # 1. 새 마디 삽입 위치(인덱스) 계산
        insert_idx = len(self.score.measures)
        for i, m in enumerate(self.score.measures):
            if m.mapped_page > page_idx:
                insert_idx = i
                break
            if m.mapped_page == page_idx:
                my = m.bbox_y1 or 0
                mx = m.bbox_x1 or 0
                # Y가 70픽셀 이상 차이나면 다음 줄(시스템)로 간주
                if my > y + 70:
                    insert_idx = i
                    break
                elif abs(my - y) <= 70: # 같은 줄(시스템)
                    if mx > x:
                        insert_idx = i
                        break
                        
        # 2. 새 마디 번호 생성
        if insert_idx == 0:
            new_number = 1
        else:
            new_number = self.score.measures[insert_idx - 1].number + 1
            
        new_measure = MeasureData(
            number=new_number,
            mapped_page=page_idx,
            bbox_x1=x, bbox_y1=y - 10,
            bbox_x2=x + 120, bbox_y2=y + 110,
            notes=[]
        )
        self.score.measures.insert(insert_idx, new_measure)
        self.score.total_measures += 1
        
        # 3. 삽입된 이후 마디들의 번호 1씩 증가 (밀어내기)
        for i in range(insert_idx + 1, len(self.score.measures)):
            self.score.measures[i].number += 1
            
        # 4. XML Tree에 <measure> 태그 주입 및 번호 갱신 (저장 시 필수)
        if self.score.xml_tree and self.score.root_element is not None:
            import xml.etree.ElementTree as ET
            for part in self.score.root_element.findall("part"):
                m_elems = part.findall("measure")
                new_m_elem = ET.Element("measure")
                new_m_elem.set("number", str(new_number))
                
                target_idx = len(m_elems)
                for k, elem in enumerate(m_elems):
                    num_str = elem.get("number")
                    if num_str and num_str.isdigit() and int(num_str) >= new_number:
                        target_idx = k
                        break
                        
                if target_idx < len(m_elems):
                    ref_elem = m_elems[target_idx]
                    p_children = list(part)
                    c_idx = p_children.index(ref_elem)
                    part.insert(c_idx, new_m_elem)
                else:
                    part.append(new_m_elem)
                    
                # 밀어낸 마디들의 XML 속성 번호도 1씩 증가
                for k in range(target_idx, len(m_elems)):
                    old_num = m_elems[k].get("number")
                    if old_num and old_num.isdigit():
                        m_elems[k].set("number", str(int(old_num) + 1))
                        
        self.render_current_page()
        self.status_bar.showMessage(f"새 마디(M{new_number}) 영역이 성공적으로 생성되었습니다. (전체: {self.score.total_measures})")

    def create_note_at(self, x: float, y: float, pitch: str = "C4"):
        """클릭한 위치의 Y 픽셀 좌표를 기반으로 Pitch(음높이: C4, G4, E5 등) 및 Staff(건반)를 자동 판별하여 추가합니다."""
        if not self.score or not self.score.measures:
            return

        # 편집 수행 전 현재 전체 악보 2D 좌표 스냅샷 백업
        auto_pitch, auto_staff = detect_pitch_from_y(y)
        final_pitch = auto_pitch if pitch == "C4" else pitch
        self.undo_manager.push_snapshot(self.score, f"음표 추가 ({final_pitch})")

        target_m = None
        for m in self.score.measures:
            if m.mapped_page == self.current_page_idx and m.bbox_x1 is not None and m.bbox_x2 is not None:
                if m.bbox_x1 <= x <= m.bbox_x2 and m.bbox_y1 - 50 <= y <= m.bbox_y2 + 50:
                    target_m = m
                    break

        if not target_m:
            p_measures = [m for m in self.score.measures if m.mapped_page == self.current_page_idx]
            target_m = p_measures[-1] if p_measures else self.score.measures[-1]

        n_idx = len(target_m.notes)
        new_note = NoteData(
            id=f"m{target_m.number}_c{n_idx}_{uuid.uuid4().hex[:6]}",
            measure_number=target_m.number,
            note_index=n_idx,
            pitch=final_pitch,
            is_rest=(final_pitch.lower() == "rest"),
            duration=1,
            beat_position=float(n_idx),
            staff=auto_staff,
            mapped_page=self.current_page_idx,
            mapped_x=x,
            mapped_y=y
        )
        target_m.notes.append(new_note)
        self.render_current_page()

        midi_num = self._pitch_to_midi(final_pitch)
        self.status_bar.showMessage(f"🎵 Y좌표 기반 음높이 자동 매칭: {final_pitch} (🎹 피아노 건반 {midi_num}번 매칭 완료) | (X: {int(x)}, Y: {int(y)})")

    def duplicate_note(self, orig_note: NoteData):
        """선택한 음표 점 1개만 정확히 복제합니다 (원본 노드의 파트 색상 및 음높이 100% 보존)."""
        if not self.score or not self.score.measures or not orig_note:
            return

        m_data = next((m for m in self.score.measures if any(n is orig_note for n in m.notes)), None)
        if not m_data:
            m_num = orig_note.measure_number
            m_data = next((m for m in self.score.measures if m.number == m_num), None)
        if not m_data:
            return

        n_idx = len(m_data.notes)
        new_x = (orig_note.mapped_x or 0.0) + 15.0
        new_y = orig_note.mapped_y or 0.0

        target_staff = orig_note.staff if orig_note.staff in (1, 2) else None
        auto_pitch, auto_staff = detect_pitch_from_y(new_y, force_staff=target_staff)
        final_staff = target_staff if target_staff else auto_staff
        pitch_val = orig_note.pitch if orig_note.pitch else auto_pitch

        self.undo_manager.push_snapshot(self.score, f"음표 점 1개 복제 ({pitch_val})")

        cloned_note = NoteData(
            id=f"m{m_data.number}_d{n_idx}_{uuid.uuid4().hex[:6]}",
            measure_number=m_data.number,
            note_index=n_idx,
            pitch=pitch_val,
            is_rest=orig_note.is_rest,
            duration=orig_note.duration,
            beat_position=orig_note.beat_position + 0.5,
            voice=orig_note.voice,
            staff=final_staff,
            mapped_page=orig_note.mapped_page,
            mapped_x=new_x,
            mapped_y=new_y
        )
        m_data.notes.append(cloned_note)
        self.render_current_page()

        # 복제 완료 후 새로 복제된 단 1개의 음표 점만 포커스 선택
        self.canvas_view.scene_obj.clearSelection()
        for item in self.canvas_view.note_items:
            if item.note_data is cloned_note or item.note_data.id == cloned_note.id:
                item.setSelected(True)
                break

        part_str = "🟢 높은음자리 (오른손)" if final_staff == 1 else "🔵 낮은음자리 (왼손)"
        if orig_note.is_rest: part_str = "🟡 쉼표 (Rest)"
        midi_num = self._pitch_to_midi(pitch_val)
        self.status_bar.showMessage(f"📋 선택한 음표 점 1개 복제 완료: {pitch_val} | 파트: {part_str} (🎹 건반 MIDI {midi_num}번 매칭)")

    def _pitch_to_midi(self, pitch_str: str) -> int:
        if not pitch_str or pitch_str == "Rest": return 60
        step = pitch_str[0].upper()
        octave_char = pitch_str[-1]
        try:
            octave = int(octave_char)
        except ValueError:
            octave = 4
        step_map = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}
        base = step_map.get(step, 0)
        alter = 0
        if '#' in pitch_str: alter = 1
        elif 'b' in pitch_str: alter = -1
        return (octave + 1) * 12 + base + alter

    def create_measure_at(self, x: float, y: float):
        """클릭한 위치에 새로운 마디 영역 박스를 생성합니다."""
        if not self.score:
            return

        new_m_num = self.score.total_measures + 1
        self.undo_manager.push_snapshot(self.score, f"마디 생성 (M{new_m_num})")

        new_m = MeasureData(
            number=new_m_num,
            mapped_page=self.current_page_idx,
            bbox_x1=x,
            bbox_y1=y,
            bbox_x2=x + 200.0,
            bbox_y2=y + 120.0,
            notes=[]
        )
        self.score.measures.append(new_m)
        self.score.total_measures = len(self.score.measures)
        self.control_panel.update_page_info(self.current_page_idx, self.pdf_renderer.page_count, self.score)
        self.render_current_page()
        self.status_bar.showMessage(f"➕ 새 마디 영역 M{new_m_num} 추가 완료 (X: {int(x)}, Y: {int(y)})")

    def delete_selected(self):
        """선택된 음표 점(또는 마디 영역)만 정확히 삭제합니다."""
        if not self.score:
            return

        selected_items = self.canvas_view.scene_obj.selectedItems()
        if not selected_items:
            return

        self.undo_manager.push_snapshot(self.score, f"선택 항목 {len(selected_items)}개 삭제")

        deleted_notes = 0
        deleted_measures = 0

        for item in selected_items:
            if isinstance(item, InteractiveNoteItem):
                note = item.note_data
                for m in self.score.measures:
                    if any(n is note for n in m.notes):
                        m.notes = [n for n in m.notes if n is not note]
                        deleted_notes += 1
                        break
                    elif any(n.id == note.id for n in m.notes):
                        m.notes = [n for n in m.notes if n.id != note.id]
                        deleted_notes += 1
                        break
            elif isinstance(item, InteractiveMeasureItem):
                m_data = item.measure_data
                if m_data in self.score.measures:
                    self.score.measures.remove(m_data)
                    self.score.total_measures = len(self.score.measures)
                    deleted_measures += 1

        self.control_panel.update_page_info(self.current_page_idx, self.pdf_renderer.page_count, self.score)
        self.render_current_page()
        self.status_bar.showMessage(f"🗑️ 선택한 음표 점 {deleted_notes}개 삭제 완료")

    def delete_measure(self, m_data: MeasureData):
        """특정 마디 영역 박스를 우클릭 메뉴를 통해 삭제합니다."""
        if not self.score or not m_data:
            return

        self.undo_manager.push_snapshot(self.score, f"마디 M{m_data.number} 삭제")
        if m_data in self.score.measures:
            self.score.measures.remove(m_data)
            self.score.total_measures = len(self.score.measures)

        self.control_panel.update_page_info(self.current_page_idx, self.pdf_renderer.page_count, self.score)
        self.render_current_page()
        self.status_bar.showMessage(f"🗑️ 마디 M{m_data.number} 영역 삭제 완료")

    def delete_single_note(self, note: NoteData):
        """선택/우클릭 지정한 단 1개의 음표 점만 정확하게 삭제합니다."""
        if not self.score or not note:
            return

        self.undo_manager.push_snapshot(self.score, f"음표 점 1개 삭제 ({note.pitch})")

        deleted = False
        for m in self.score.measures:
            if any(n is note for n in m.notes):
                m.notes = [n for n in m.notes if n is not note]
                deleted = True
                break
            elif any(n.id == note.id for n in m.notes):
                m.notes = [n for n in m.notes if n.id != note.id]
                deleted = True
                break

        if deleted:
            self.control_panel.update_page_info(self.current_page_idx, self.pdf_renderer.page_count, self.score)
            self.render_current_page()
            self.status_bar.showMessage(f"🗑️ 선택한 음표 점 1개 삭제 완료 ({note.pitch})")

    def apply_measure_resize(self, m_num: int, delta_w: float):
        """특정 마디의 가로 폭(Width)을 delta_w만큼 확장/축소하고 내부 음표를 비례 배치합니다."""
        if not self.score or not self.score.measures:
            return

        m_data = next((m for m in self.score.measures if m.number == m_num), None)
        if not m_data or m_data.bbox_x1 is None or m_data.bbox_x2 is None:
            return

        self.undo_manager.push_snapshot(self.score, f"마디 M{m_num} 가로 폭 조절")

        old_w = max(1.0, m_data.bbox_x2 - m_data.bbox_x1)
        new_w = max(15.0, old_w + delta_w)
        x1 = m_data.bbox_x1
        m_data.bbox_x2 = x1 + new_w

        # 내부 음표 mapped_x 비례 비율 재계산 (비율 폭주 방지 clamp 적용)
        for note in m_data.notes:
            if note.mapped_x is not None:
                ratio = (note.mapped_x - x1) / old_w
                ratio = min(max(0.0, ratio), 1.0)
                note.mapped_x = x1 + ratio * new_w

        self.render_current_page()
        self.status_bar.showMessage(f"📏 마디 M{m_num} 가로 폭 조절 완료 (새 가로폭: {int(new_w)}px)")

    def refresh_measure_numbers(self):
        """삭제 등으로 인해 마디 번호가 끊긴 경우, 순차적으로 마디 번호를 일괄 재정렬(새로고침)합니다."""
        if not self.score or not self.score.measures:
            return
            
        self.undo_manager.push_snapshot(self.score, "마디 번호 일괄 새로고침")
        
        # 1. 내부 MeasureData 번호 재정렬
        for idx, m_data in enumerate(self.score.measures):
            m_data.number = idx + 1
            
        # 2. XML Tree 속성 갱신 (저장용)
        if self.score.xml_tree and self.score.root_element is not None:
            for part in self.score.root_element.findall("part"):
                m_elems = part.findall("measure")
                for k, elem in enumerate(m_elems):
                    elem.set("number", str(k + 1))
                    
        self.control_panel.update_page_info(self.current_page_idx, self.pdf_renderer.page_count, self.score)
        self.render_current_page()
        self.status_bar.showMessage("🔄 마디 영역 번호가 순차적으로 일괄 새로고침 되었습니다.")


    def apply_page_offset(self, dx: float, dy: float):
        """현재 페이지의 모든 마디 및 음표 점 오버레이를 dx, dy만큼 일괄 이동합니다."""
        if not self.score or not self.score.measures:
            return

        self.undo_manager.push_snapshot(self.score, f"페이지 {self.current_page_idx + 1} 오버레이 일괄 이동")

        moved_count = 0
        for m in self.score.measures:
            if m.mapped_page == self.current_page_idx:
                if m.bbox_x1 is not None: m.bbox_x1 += dx
                if m.bbox_x2 is not None: m.bbox_x2 += dx
                if m.bbox_y1 is not None: m.bbox_y1 += dy
                if m.bbox_y2 is not None: m.bbox_y2 += dy

                for note in m.notes:
                    if note.mapped_x is not None: note.mapped_x += dx
                    if note.mapped_y is not None: note.mapped_y += dy
                moved_count += 1

        if moved_count > 0:
            self.render_current_page()
            self.status_bar.showMessage(f"📐 페이지 {self.current_page_idx + 1} 오버레이 일괄 이동 완료 (X: {int(dx)}px, Y: {int(dy)}px)")

    def update_overlay_visibility(self, show_measures: bool, show_notes: bool):
        self.canvas_view.set_overlay_visibility(show_measures, show_notes)

    def save_project_dialog(self):
        """현재 작업 세션 전체(PDF 경로, MusicXML 경로, 보정된 2D 좌표)를 프로젝트 파일(.nfsp)로 저장합니다."""
        if not self.pdf_loaded or not self.score:
            QMessageBox.warning(self, "경고", "저장할 작업 세션 데이터(PDF 및 MusicXML)가 없습니다.")
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self, "프로젝트 세션 저장", "sync_project.nfsp", "NoteFlow Project Files (*.nfsp *.json)"
        )
        if file_path:
            try:
                pdf_p = getattr(self, 'current_pdf_path', '')
                xml_p = getattr(self, 'current_xml_path', '')
                self.xml_exporter.export_project_session(
                    self.score, pdf_p, xml_p, self.current_page_idx, file_path
                )
                self.status_bar.showMessage(f"💾 프로젝트 세션 저장 완료: {file_path}")
                QMessageBox.information(self, "프로젝트 저장 완료", f"현재 작업 세션이 성공적으로 저장되었습니다:\n{file_path}\n\n다음에 언제든지 불러와서 계속 작업하실 수 있습니다.")
            except Exception as e:
                QMessageBox.critical(self, "저장 실패", f"프로젝트 세션 저장 중 오류가 발생했습니다:\n{str(e)}")

    def load_project_dialog(self):
        """저장된 프로젝트 세션 파일(.nfsp)을 불러와 이전 작업 상태를 100% 복원합니다."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "프로젝트 세션 불러오기", "", "NoteFlow Project Files (*.nfsp *.json)"
        )
        if file_path:
            self.load_project_file(file_path)

    def load_project_file(self, session_path: str):
        try:
            session_data = self.xml_exporter.load_project_session(session_path)
            pdf_path = session_data.get("pdf_path")
            xml_path = session_data.get("xml_path")
            saved_page = session_data.get("current_page", 0)

            # PDF 로드
            if pdf_path and os.path.exists(pdf_path):
                self.load_pdf_file(pdf_path)
            
            # MusicXML 기본 파싱
            if xml_path and os.path.exists(xml_path):
                self.score = self.xml_parser.parse(xml_path)
                self.xml_loaded = True
                self.current_xml_path = xml_path
                self.control_panel.lbl_xml_info.setText(f"{os.path.basename(xml_path)}\n({self.score.total_measures} 마디)")

            # 세션에 저장된 보정 마디 및 음표 2D 좌표 복원
            s_measures = session_data.get("score", {}).get("measures", [])
            s_map = {m["number"]: m for m in s_measures}

            if self.score and self.score.measures:
                for m in self.score.measures:
                    if m.number in s_map:
                        sm = s_map[m.number]
                        m.mapped_page = sm.get("page", 0)
                        bbox = sm.get("bbox", {})
                        m.bbox_x1 = bbox.get("x1")
                        m.bbox_y1 = bbox.get("y1")
                        m.bbox_x2 = bbox.get("x2")
                        m.bbox_y2 = bbox.get("y2")

                        notes_data = sm.get("notes", [])
                        n_map = {n["id"]: n for n in notes_data}
                        for note in m.notes:
                            if note.id in n_map:
                                sn = n_map[note.id]
                                note.mapped_page = sn.get("page", 0)
                                note.mapped_x = sn.get("x")
                                note.mapped_y = sn.get("y")
                                if "staff" in sn: note.staff = sn["staff"]
                                if "pitch" in sn: note.pitch = sn["pitch"]
                                if "is_rest" in sn: note.is_rest = sn["is_rest"]

            page_count = self.pdf_renderer.page_count if self.pdf_loaded else 1
            self.change_page(min(saved_page, page_count - 1))
            self.status_bar.showMessage(f"📂 프로젝트 세션 복원 완료: {session_path}")
            QMessageBox.information(self, "세션 복원 완료", f"이전 작업 세션이 성공적으로 복원되었습니다!\n(페이지: {saved_page + 1})")
        except Exception as e:
            QMessageBox.critical(self, "세션 복원 실패", f"프로젝트 세션을 불러오는 도중 오류가 발생했습니다:\n{str(e)}")

    def save_xml_dialog(self):
        if not self.score:
            QMessageBox.warning(self, "경고", "저장할 MusicXML 데이터가 없습니다.")
            return

        default_path = getattr(self, 'current_xml_path', '') or "synced_score.musicxml"
        file_path, _ = QFileDialog.getSaveFileName(
            self, "완성된 MusicXML 저장", default_path, "MusicXML Files (*.musicxml *.xml)"
        )
        if file_path:
            try:
                self.xml_exporter.export_musicxml(self.score, file_path)
                self.current_xml_path = file_path
                self.control_panel.lbl_xml_info.setText(f"{os.path.basename(file_path)}\n({self.score.total_measures} 마디)")
                self.status_bar.showMessage(f"MusicXML 파일 저장 완료: {file_path}")
                QMessageBox.information(self, "저장 완료", f"보정된 MusicXML 파일이 성공적으로 저장되었습니다:\n{file_path}")
            except Exception as e:
                QMessageBox.critical(self, "저장 실패", f"MusicXML 저장 중 오류가 발생했습니다:\n{str(e)}")

    def save_json_dialog(self):
        if not self.score:
            QMessageBox.warning(self, "경고", "저장할 싱크 데이터가 없습니다.")
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self, "비디오 싱크 JSON 저장", "sync_data.json", "JSON Files (*.json)"
        )
        if file_path:
            try:
                self.xml_exporter.export_sync_json(self.score, file_path)
                self.status_bar.showMessage(f"싱크 JSON 파일 저장 완료: {file_path}")
                QMessageBox.information(self, "저장 완료", f"비디오 싱크 JSON 파일이 성공적으로 저장되었습니다:\n{file_path}")
            except Exception as e:
                QMessageBox.critical(self, "저장 실패", f"JSON 저장 중 오류가 발생했습니다:\n{str(e)}")

    def _update_coords_status(self, x: float, y: float):
        self.status_bar.showMessage(f"페이지 {self.current_page_idx + 1} | 좌표: X={int(x)}, Y={int(y)}")

    # Drag and Drop 지원
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def keyPressEvent(self, event):
        """키보드 Del 키로 선택 음표 삭제, 좌/우 방향키 및 PageUp/PageDown 키로 동기화 페이지 이동 지원"""
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.delete_selected()
            event.accept()
            return

        if event.key() in (Qt.Key.Key_Left, Qt.Key.Key_PageUp):
            if self.current_page_idx > 0:
                self.change_page(self.current_page_idx - 1)
            event.accept()
        elif event.key() in (Qt.Key.Key_Right, Qt.Key.Key_PageDown):
            if self.pdf_loaded and self.current_page_idx < self.pdf_renderer.page_count - 1:
                self.change_page(self.current_page_idx + 1)
            event.accept()
        else:
            super().keyPressEvent(event)
