from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QGroupBox,
    QCheckBox, QSpinBox, QSlider, QFrame, QFileDialog, QMessageBox, QComboBox,
    QScrollArea
)
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QFont, QIcon

class ControlPanel(QWidget):
    open_pdf_signal = pyqtSignal()
    open_xml_signal = pyqtSignal()
    auto_sync_signal = pyqtSignal()
    precision_calc_signal = pyqtSignal()
    save_xml_signal = pyqtSignal()
    save_json_signal = pyqtSignal()
    save_project_signal = pyqtSignal()
    load_project_signal = pyqtSignal()
    page_changed_signal = pyqtSignal(int)
    visibility_toggled_signal = pyqtSignal(bool, bool)
    offset_applied_signal = pyqtSignal(float, float)
    measure_resized_signal = pyqtSignal(int, float)
    refresh_measure_nums_signal = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(320)
        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        scroll_area = QScrollArea(self)
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setStyleSheet("""
            QScrollArea {
                background-color: #F8FAFC;
                border-left: 1px solid #E2E8F0;
            }
            QScrollBar:vertical {
                border: none;
                background: #F1F5F9;
                width: 8px;
                margin: 0px 0px 0px 0px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background: #94A3B8;
                min-height: 20px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical:hover {
                background: #64748B;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)

        container = QWidget()
        container.setStyleSheet("""
            QWidget {
                background-color: #0F172A;
            }
            QGroupBox {
                font-weight: bold;
                font-size: 12px;
                color: #38BDF8;
                border: 1px solid #334155;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 12px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
                color: #38BDF8;
            }
            QLabel {
                color: #E2E8F0;
                font-size: 11px;
            }
            QCheckBox {
                color: #F8FAFC;
                font-weight: bold;
                font-size: 11px;
            }
            QSpinBox, QComboBox {
                background-color: #1E293B;
                color: #F8FAFC;
                border: 1px solid #475569;
                border-radius: 4px;
                padding: 4px;
                font-weight: bold;
            }
            QSpinBox::up-button, QSpinBox::down-button {
                background-color: #334155;
            }
        """)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(14)

        # 1. 제목 및 로고
        header = QLabel("NoteFlow Sheet Sync Studio")
        header_font = QFont("Segoe UI", 12, QFont.Weight.Bold)
        header.setFont(header_font)
        header.setStyleSheet("color: #38BDF8; margin-bottom: 4px; font-weight: bold;")
        layout.addWidget(header)

        # 2. 파일 로딩 그룹
        file_group = QGroupBox("📁 1. 파일 불러오기")
        fg_layout = QVBoxLayout(file_group)

        self.btn_load_pdf = QPushButton("📄 PDF 악보 로드")
        self.btn_load_pdf.setStyleSheet("""
            QPushButton {
                background-color: #2563EB; color: white; font-weight: bold;
                padding: 8px; border-radius: 6px; border: none;
            }
            QPushButton:hover { background-color: #1D4ED8; }
        """)
        self.btn_load_pdf.clicked.connect(self.open_pdf_signal.emit)

        self.lbl_pdf_info = QLabel("선택된 PDF 없음")
        self.lbl_pdf_info.setStyleSheet("color: #94A3B8; font-size: 11px;")
        self.lbl_pdf_info.setWordWrap(True)

        self.btn_load_xml = QPushButton("🎼 MusicXML 로드")
        self.btn_load_xml.setStyleSheet("""
            QPushButton {
                background-color: #7C3AED; color: white; font-weight: bold;
                padding: 8px; border-radius: 6px; border: none;
            }
            QPushButton:hover { background-color: #6D28D9; }
        """)
        self.btn_load_xml.clicked.connect(self.open_xml_signal.emit)

        self.lbl_xml_info = QLabel("선택된 MusicXML 없음")
        self.lbl_xml_info.setStyleSheet("color: #94A3B8; font-size: 11px;")
        self.lbl_xml_info.setWordWrap(True)

        fg_layout.addWidget(self.btn_load_pdf)
        fg_layout.addWidget(self.lbl_pdf_info)
        fg_layout.addWidget(self.btn_load_xml)
        fg_layout.addWidget(self.lbl_xml_info)
        layout.addWidget(file_group)

        # 3. 페이지 탐색 그룹
        nav_group = QGroupBox("📖 2. 악보 페이지 이동")
        ng_layout = QVBoxLayout(nav_group)

        self.combo_page = QComboBox()
        self.combo_page.currentIndexChanged.connect(self._on_combo_page_changed)

        btn_box = QHBoxLayout()
        btn_nav_style = """
            QPushButton {
                background-color: #334155; color: #F8FAFC; font-weight: bold;
                padding: 5px 8px; border-radius: 4px; border: 1px solid #475569;
            }
            QPushButton:hover { background-color: #475569; }
        """
        self.btn_prev_page = QPushButton("◀ 이전")
        self.btn_prev_page.setStyleSheet(btn_nav_style)
        self.btn_prev_page.clicked.connect(self._prev_page)

        self.lbl_page = QLabel("0 / 0")
        self.lbl_page.setStyleSheet("color: #F8FAFC; font-weight: bold;")
        self.lbl_page.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.btn_next_page = QPushButton("다음 ▶")
        self.btn_next_page.setStyleSheet(btn_nav_style)
        self.btn_next_page.clicked.connect(self._next_page)

        btn_box.addWidget(self.btn_prev_page)
        btn_box.addWidget(self.lbl_page)
        btn_box.addWidget(self.btn_next_page)

        ng_layout.addWidget(self.combo_page)
        ng_layout.addLayout(btn_box)
        layout.addWidget(nav_group)

        # 4. 자동 싱크 및 정밀 계산 그룹 (Primary Actions)
        sync_group = QGroupBox("⚡ 3. 자동 맵핑 & 정밀 계산")
        sg_layout = QVBoxLayout(sync_group)

        self.btn_auto_sync = QPushButton("✨ 싱크 맞추기 (Auto-Align)")
        self.btn_auto_sync.setStyleSheet("""
            QPushButton {
                background-color: #059669; color: white; font-weight: bold; font-size: 12px;
                padding: 9px; border-radius: 6px; border: none;
            }
            QPushButton:hover { background-color: #047857; }
            QPushButton:disabled { background-color: #334155; color: #64748B; }
        """)
        self.btn_auto_sync.setToolTip("PDF 악보를 스캔하여 마디 및 음표를 오선지에 자동 초기 배치합니다.")
        self.btn_auto_sync.clicked.connect(self.auto_sync_signal.emit)

        self.btn_precision_calc = QPushButton("🔬 정밀 계산 (음계·건반·박자)")
        self.btn_precision_calc.setStyleSheet("""
            QPushButton {
                background-color: #6366F1; color: white; font-weight: bold; font-size: 13px;
                padding: 11px; border-radius: 8px; border: none;
            }
            QPushButton:hover { background-color: #4F46E5; }
            QPushButton:disabled { background-color: #334155; color: #64748B; }
        """)
        self.btn_precision_calc.setToolTip("수동 조정한 마디/음표 위치를 기반으로 오선지 줄/칸 음계, 건반(높은/낮은음자리), 박자 및 MusicXML을 정밀 재계산합니다.")
        self.btn_precision_calc.clicked.connect(self.precision_calc_signal.emit)

        sg_layout.addWidget(self.btn_auto_sync)
        sg_layout.addWidget(self.btn_precision_calc)
        layout.addWidget(sync_group)

        # 5. 오선지 위치 미세 일괄 보정 그룹
        calib_group = QGroupBox("📐 4. 전구간 오버레이 오프셋 보정")
        cg_layout = QVBoxLayout(calib_group)

        lbl_y = QLabel("Y축 수직 오프셋 (위/아래 이동):")
        lbl_y.setStyleSheet("font-size: 11px; color: #CBD5E1;")
        
        y_box = QHBoxLayout()
        self.spin_offset_y = QSpinBox()
        self.spin_offset_y.setRange(-1000, 1000)
        self.spin_offset_y.setValue(0)
        self.spin_offset_y.setSuffix(" px")

        self.btn_apply_y = QPushButton("Y축 이동")
        self.btn_apply_y.setStyleSheet(btn_nav_style)
        self.btn_apply_y.clicked.connect(self._on_offset_applied)

        y_box.addWidget(self.spin_offset_y)
        y_box.addWidget(self.btn_apply_y)

        lbl_x = QLabel("X축 가로 오프셋 (좌/우 이동):")
        lbl_x.setStyleSheet("font-size: 11px; color: #CBD5E1;")

        x_box = QHBoxLayout()
        self.spin_offset_x = QSpinBox()
        self.spin_offset_x.setRange(-1000, 1000)
        self.spin_offset_x.setValue(0)
        self.spin_offset_x.setSuffix(" px")

        self.btn_apply_x = QPushButton("X축 이동")
        self.btn_apply_x.setStyleSheet(btn_nav_style)
        self.btn_apply_x.clicked.connect(self._on_offset_applied)

        x_box.addWidget(self.spin_offset_x)
        x_box.addWidget(self.btn_apply_x)

        cg_layout.addWidget(lbl_y)
        cg_layout.addLayout(y_box)
        cg_layout.addWidget(lbl_x)
        cg_layout.addLayout(x_box)
        layout.addWidget(calib_group)

        # 6. 개별 마디 가로 폭 & 위치 정밀 조절 그룹
        m_adjust_group = QGroupBox("📏 5. 개별 마디 가로 폭/위치 조절")
        mg_layout = QVBoxLayout(m_adjust_group)

        self.combo_select_m = QComboBox()

        lbl_mw = QLabel("선택 마디 가로 폭 늘리기/줄이기:")
        lbl_mw.setStyleSheet("font-size: 11px; color: #CBD5E1;")
        
        w_box = QHBoxLayout()
        self.spin_m_width = QSpinBox()
        self.spin_m_width.setRange(-500, 500)
        self.spin_m_width.setValue(0)
        self.spin_m_width.setSuffix(" px")

        self.btn_apply_mw = QPushButton("폭 적용")
        self.btn_apply_mw.setStyleSheet(btn_nav_style)
        self.btn_apply_mw.clicked.connect(self._on_measure_resized)

        self.btn_refresh_m_nums = QPushButton("🔄 세로 마디 영역 번호 새로고침")
        self.btn_refresh_m_nums.setStyleSheet(btn_nav_style)
        self.btn_refresh_m_nums.clicked.connect(self.refresh_measure_nums_signal.emit)

        w_box.addWidget(self.spin_m_width)
        w_box.addWidget(self.btn_apply_mw)

        mg_layout.addWidget(self.combo_select_m)
        mg_layout.addWidget(lbl_mw)
        mg_layout.addLayout(w_box)
        mg_layout.addWidget(self.btn_refresh_m_nums)
        layout.addWidget(m_adjust_group)

        # 7. 오버레이 옵션
        view_group = QGroupBox("👁️ 6. 시각화 오버레이 설정")
        vg_layout = QVBoxLayout(view_group)

        self.chk_measures = QCheckBox("마디 구분 영역 (BBoxes)")
        self.chk_measures.setChecked(True)
        self.chk_measures.stateChanged.connect(self._emit_visibility)

        self.chk_notes = QCheckBox("음표 위치 점 오버레이")
        self.chk_notes.setChecked(True)
        self.chk_notes.stateChanged.connect(self._emit_visibility)

        vg_layout.addWidget(self.chk_measures)
        vg_layout.addWidget(self.chk_notes)
        layout.addWidget(view_group)

        # 8. 완성 저장 및 프로젝트 세션 그룹
        save_group = QGroupBox("💾 7. 보정 파일 및 프로젝트 저장")
        save_layout = QVBoxLayout(save_group)

        self.btn_save_project = QPushButton("💾 프로젝트 세션 저장 (.nfsp)")
        self.btn_save_project.setStyleSheet("""
            QPushButton {
                background-color: #7C3AED; color: white; font-weight: bold;
                padding: 9px; border-radius: 6px; border: none;
            }
            QPushButton:hover { background-color: #6D28D9; }
        """)
        self.btn_save_project.clicked.connect(self.save_project_signal.emit)

        self.btn_load_project = QPushButton("📂 프로젝트 세션 불러오기 (.nfsp)")
        self.btn_load_project.setStyleSheet("""
            QPushButton {
                background-color: #334155; color: white; font-weight: bold;
                padding: 9px; border-radius: 6px; border: 1px solid #475569;
            }
            QPushButton:hover { background-color: #475569; }
        """)
        self.btn_load_project.clicked.connect(self.load_project_signal.emit)

        self.btn_save_xml = QPushButton("🎼 완성된 MusicXML 저장")
        self.btn_save_xml.setStyleSheet("""
            QPushButton {
                background-color: #0284C7; color: white; font-weight: bold;
                padding: 9px; border-radius: 6px; border: none;
            }
            QPushButton:hover { background-color: #0369A1; }
        """)
        self.btn_save_xml.clicked.connect(self.save_xml_signal.emit)

        self.btn_save_json = QPushButton("🎬 비디오 싱크 JSON 저장")
        self.btn_save_json.setStyleSheet("""
            QPushButton {
                background-color: #475569; color: white; font-weight: bold;
                padding: 9px; border-radius: 6px; border: none;
            }
            QPushButton:hover { background-color: #334155; }
        """)
        self.btn_save_json.clicked.connect(self.save_json_signal.emit)

        save_layout.addWidget(self.btn_save_project)
        save_layout.addWidget(self.btn_load_project)
        save_layout.addWidget(self.btn_save_xml)
        save_layout.addWidget(self.btn_save_json)
        layout.addWidget(save_group)

        layout.addStretch()

        scroll_area.setWidget(container)
        main_layout.addWidget(scroll_area)

        self.current_page = 0
        self.total_pages = 0

    def update_page_info(self, current_page: int, total_pages: int, score = None):
        self.current_page = current_page
        self.total_pages = total_pages

        self.combo_page.blockSignals(True)
        self.combo_page.clear()
        self.combo_select_m.blockSignals(True)
        self.combo_select_m.clear()

        if total_pages > 0:
            self.lbl_page.setText(f"{current_page + 1} / {total_pages}")
            for p in range(total_pages):
                label_text = f"페이지 {p + 1}"
                if score and score.measures:
                    p_measures = [m.number for m in score.measures if m.mapped_page == p]
                    if p_measures:
                        label_text += f" (M{min(p_measures)} ~ M{max(p_measures)})"
                self.combo_page.addItem(label_text)
            self.combo_page.setCurrentIndex(current_page)

            if score and score.measures:
                p_measures_objs = [m for m in score.measures if m.mapped_page == current_page]
                for m in p_measures_objs:
                    self.combo_select_m.addItem(f"마디 M{m.number}", m.number)
        else:
            self.lbl_page.setText("0 / 0")

        self.combo_page.blockSignals(False)
        self.combo_select_m.blockSignals(False)

    def _on_combo_page_changed(self, index: int):
        if index >= 0 and index != self.current_page:
            self.current_page = index
            self.page_changed_signal.emit(index)

    def _on_offset_applied(self):
        dx = float(self.spin_offset_x.value())
        dy = float(self.spin_offset_y.value())
        self.offset_applied_signal.emit(dx, dy)
        self.spin_offset_x.setValue(0)
        self.spin_offset_y.setValue(0)

    def _on_measure_resized(self):
        m_num = self.combo_select_m.currentData()
        if m_num is not None:
            delta_w = float(self.spin_m_width.value())
            self.measure_resized_signal.emit(int(m_num), delta_w)
            self.spin_m_width.setValue(0)

    def _prev_page(self):
        if self.current_page > 0:
            self.current_page -= 1
            self.page_changed_signal.emit(self.current_page)

    def _next_page(self):
        if self.current_page < self.total_pages - 1:
            self.current_page += 1
            self.page_changed_signal.emit(self.current_page)

    def _emit_visibility(self):
        self.visibility_toggled_signal.emit(
            self.chk_measures.isChecked(),
            self.chk_notes.isChecked()
        )
