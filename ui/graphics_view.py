import math
from PyQt6.QtWidgets import (
    QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, QGraphicsRectItem,
    QGraphicsEllipseItem, QGraphicsItem, QGraphicsLineItem, QGraphicsTextItem,
    QToolTip, QMenu, QInputDialog, QApplication
)
from PyQt6.QtCore import Qt, QRectF, QPointF, pyqtSignal
from PyQt6.QtGui import QPen, QBrush, QColor, QFont, QPainter, QCursor, QTransform
from typing import List, Optional, Callable, Tuple, Any, Dict
from core.musicxml_parser import MeasureData, NoteData
from core.undo_manager import MoveAction, EditAction, GroupAction

class InteractiveNoteItem(QGraphicsEllipseItem):
    """악보 상의 음표 위치를 나타내는 오버레이 드래그 가능 점 포인트"""
    def __init__(self, note_data: NoteData, radius: float = 6.0, on_moved_callback: Optional[Callable] = None):
        rx, ry = note_data.mapped_x or 0, note_data.mapped_y or 0
        super().__init__(-radius, -radius, radius * 2, radius * 2)
        self.setPos(rx, ry)
        self.note_data = note_data
        self.radius = radius
        self.on_moved_callback = on_moved_callback
        self.press_pos: Optional[QPointF] = None

        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable |
            QGraphicsItem.GraphicsItemFlag.ItemIsSelectable |
            QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)
        self.update_appearance()

    def update_appearance(self):
        """음표 데이터(Pitch, Staff, Rest, 좌표)에 맞춰 시각적 브러시 색상 및 툴팁 갱신"""
        midi_num = self._pitch_to_midi(self.note_data.pitch) if not self.note_data.is_rest else "N/A"

        # 색상 구분: 쉼표(노란색/황색), 오른손/높은음자리(녹색), 왼손/낮은음자리(파란색/민트색)
        if self.note_data.is_rest:
            color = QColor(255, 180, 0, 220)       # 쉼표: 황색/노란색
            staff_label = "쉼표 (Rest)"
        elif self.note_data.staff == 2:
            color = QColor(0, 170, 255, 220)       # 왼손/낮은음자리: 파란색/민트
            staff_label = "낮은음자리 (왼손)"
        else:
            color = QColor(0, 210, 110, 220)       # 오른손/높은음자리: 녹색
            staff_label = "높은음자리 (오른손)"

        self.color = color
        self.setPen(QPen(QColor(0, 40, 20), 1.5))
        self.setBrush(QBrush(color))
        rx, ry = self.note_data.mapped_x or self.pos().x(), self.note_data.mapped_y or self.pos().y()
        self.setToolTip(f"M{self.note_data.measure_number} | 음높이: {self.note_data.pitch} (🎹 건반 MIDI {midi_num}) | {staff_label} | 좌표: ({int(rx)}, {int(ry)})")

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

    def mousePressEvent(self, event):
        self.press_pos = self.pos()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if self.press_pos is not None and (self.press_pos.x() != self.pos().x() or self.press_pos.y() != self.pos().y()):
            self.note_data.mapped_x = float(self.pos().x())
            self.note_data.mapped_y = float(self.pos().y())
            self.update_appearance()
            if self.on_moved_callback:
                self.on_moved_callback(self.note_data, self.press_pos.x(), self.press_pos.y(), self.pos().x(), self.pos().y())
        self.press_pos = None

    def itemChange(self, change: QGraphicsItem.GraphicsItemChange, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange and self.scene():
            new_pos = value
            modifiers = QApplication.keyboardModifiers()

            # Shift 키를 누르고 드래그 시: 상/하(수직 음계 스냅) 또는 좌/우(수평 박자 스냅) 직교 스냅 이동
            if (modifiers & Qt.KeyboardModifier.ShiftModifier) and self.press_pos is not None:
                orig_x = self.press_pos.x()
                orig_y = self.press_pos.y()
                dx = new_pos.x() - orig_x
                dy = new_pos.y() - orig_y

                views = self.scene().views()
                if abs(dy) >= abs(dx):
                    # 1. 수직(상/하) 방향 이동: X축 고정 + Y축 오선지 줄/칸 음계별 자석 스냅
                    if views and hasattr(views[0], 'get_pitch_snap_y'):
                        snapped_y, pitch_str, staff = views[0].get_pitch_snap_y(new_pos.y(), self.note_data.pitch)
                        new_pos = QPointF(orig_x, snapped_y)
                        self.note_data.pitch = pitch_str
                        self.note_data.staff = staff
                        self.update_appearance()
                    else:
                        new_pos = QPointF(orig_x, new_pos.y())
                else:
                    # 2. 수평(좌/우) 방향 이동: Y축(음높이) 고정 + X축 음악적 박자 그리드 자석 스냅
                    if views and hasattr(views[0], 'get_beat_snap_x'):
                        snapped_x, beat_val = views[0].get_beat_snap_x(new_pos.x(), self.note_data.measure_number)
                        new_pos = QPointF(snapped_x, orig_y)
                        self.note_data.beat_position = beat_val
                        self.update_appearance()
                    else:
                        new_pos = QPointF(new_pos.x(), orig_y)

            self.note_data.mapped_x = float(new_pos.x())
            self.note_data.mapped_y = float(new_pos.y())
            return new_pos
        return super().itemChange(change, value)

    def hoverEnterEvent(self, event):
        self.setBrush(QBrush(QColor(255, 60, 120, 255)))
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self.setBrush(QBrush(self.color))
        super().hoverLeaveEvent(event)


class InteractiveMeasureItem(QGraphicsRectItem):
    """마디 바운딩 박스 오버레이 및 상/하/좌/우 드래그 크기 조절 객체"""
    def __init__(self, measure_data: MeasureData, on_moved_callback: Optional[Callable] = None):
        x1 = measure_data.bbox_x1 or 0
        y1 = measure_data.bbox_y1 or 0
        x2 = measure_data.bbox_x2 or 100
        y2 = measure_data.bbox_y2 or 100
        w = max(15.0, x2 - x1)
        h = max(15.0, y2 - y1)

        super().__init__(0, 0, w, h)
        self.setPos(x1, y1)
        self.measure_data = measure_data
        self.on_moved_callback = on_moved_callback
        self.press_pos: Optional[QPointF] = None
        self.press_item_pos: Optional[QPointF] = None
        self.press_rect: Optional[QRectF] = None
        self.active_handle: Optional[str] = None  # None, 'left', 'right', 'top', 'bottom'

        # 얇은 점선 파란색 사각형
        pen = QPen(QColor(60, 120, 255, 220), 2.0, Qt.PenStyle.DashLine)
        self.setPen(pen)
        self.setBrush(QBrush(QColor(80, 140, 255, 30)))

        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable |
            QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)

        # 마디 번호 라벨
        self.label_item = QGraphicsTextItem(f"M{measure_data.number}", self)
        self.label_item.setDefaultTextColor(QColor(20, 40, 160))
        font = QFont("Arial", 9, QFont.Weight.Bold)
        self.label_item.setFont(font)
        self.label_item.setPos(2, 2)

    def hoverMoveEvent(self, event):
        pos = event.pos()
        rect = self.rect()
        margin = 8.0

        if abs(pos.x() - rect.right()) <= margin or abs(pos.x() - rect.left()) <= margin:
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif abs(pos.y() - rect.bottom()) <= margin or abs(pos.y() - rect.top()) <= margin:
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)
        super().hoverMoveEvent(event)

    def mousePressEvent(self, event):
        pos = event.pos()
        rect = self.rect()
        margin = 8.0

        if abs(pos.x() - rect.right()) <= margin:
            self.active_handle = 'right'
        elif abs(pos.x() - rect.left()) <= margin:
            self.active_handle = 'left'
        elif abs(pos.y() - rect.bottom()) <= margin:
            self.active_handle = 'bottom'
        elif abs(pos.y() - rect.top()) <= margin:
            self.active_handle = 'top'
        else:
            self.active_handle = None

        # 테두리 핸들을 잡지 않고 마디 내부를 클릭한 경우: 마퀴(RubberBand) 드래그 선택이 원활하게 작동하도록 이벤트 무시
        if not self.active_handle:
            event.ignore()
            return

        self.press_pos = event.scenePos()
        self.press_item_pos = self.pos()
        self.press_rect = self.rect()
        self.press_note_coords = [(n.id, n.mapped_x, n.mapped_y) for n in self.measure_data.notes if n.mapped_x is not None and n.mapped_y is not None]

        super().mousePressEvent(event)

    def itemChange(self, change: QGraphicsItem.GraphicsItemChange, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange and self.scene():
            new_pos = value
            # 세로 마디 영역: Y축 수직 높이 100% 완전 고정 (오직 수평 X축 좌/우로만 이동)
            lock_y = self.press_item_pos.y() if self.press_item_pos is not None else self.pos().y()
            new_pos = QPointF(new_pos.x(), lock_y)

            w = self.rect().width()
            h = self.rect().height()
            orig_x = self.press_item_pos.x() if self.press_item_pos is not None else self.pos().x()
            orig_w = self.press_rect.width() if self.press_rect is not None else w
            self._update_measure_data(new_pos.x(), new_pos.y(), w, h, orig_x, orig_w)
            return new_pos
        return super().itemChange(change, value)

    def _snap_x(self, x_val: float, threshold: float = 14.0) -> Tuple[float, bool]:
        """PDF 악보의 인쇄된 세로 마디선 및 인접 마디 영역 경계선 X 좌표에 자석 스냅(Magnet Snap)시킵니다."""
        if not self.scene() or not hasattr(self.scene(), 'views'):
            return x_val, False
        views = self.scene().views()
        if not views or not hasattr(views[0], 'get_snap_target_xs'):
            return x_val, False

        target_xs = views[0].get_snap_target_xs(self.measure_data.number)
        best_snap = None
        min_dist = threshold + 1.0

        for tx in target_xs:
            dist = abs(x_val - tx)
            if dist <= threshold and dist < min_dist:
                min_dist = dist
                best_snap = tx

        if best_snap is not None:
            return float(best_snap), True
        return x_val, False

    def mouseMoveEvent(self, event):
        if self.active_handle and self.press_pos and self.press_rect and self.press_item_pos:
            delta = event.scenePos() - self.press_pos
            orig_rect = self.press_rect
            orig_pos = self.press_item_pos

            new_x = orig_pos.x()
            new_y = orig_pos.y()
            new_w = orig_rect.width()
            new_h = orig_rect.height()
            is_snapped = False

            if self.active_handle == 'right':
                cand_right = orig_pos.x() + max(15.0, orig_rect.width() + delta.x())
                snapped_right, is_snapped = self._snap_x(cand_right)
                new_w = max(15.0, snapped_right - orig_pos.x())
            elif self.active_handle == 'left':
                cand_left = orig_pos.x() + delta.x()
                snapped_left, is_snapped = self._snap_x(cand_left)
                new_x = snapped_left
                new_w = max(15.0, (orig_pos.x() + orig_rect.width()) - snapped_left)
            elif self.active_handle == 'bottom':
                new_h = max(15.0, orig_rect.height() + delta.y())
            elif self.active_handle == 'top':
                new_y = orig_pos.y() + delta.y()
                new_h = max(15.0, orig_rect.height() - delta.y())

            if is_snapped:
                snap_pen = QPen(QColor(6, 182, 212, 255), 2.5, Qt.PenStyle.SolidLine)
                self.setPen(snap_pen)
            else:
                pen = QPen(QColor(60, 120, 255, 220), 2.0, Qt.PenStyle.DashLine)
                self.setPen(pen)

            self.setPos(new_x, new_y)
            self.setRect(0, 0, new_w, new_h)
            self._update_measure_data(new_x, new_y, new_w, new_h, orig_pos.x(), orig_rect.width())
        elif self.press_pos and self.press_item_pos and self.press_rect:
            # 몸통 드래그 시: Y축 수직 높이 100% 고정, 오직 좌/우(X축) 수평 슬라이딩 이동 & 세로 마디선 자석 스냅
            delta = event.scenePos() - self.press_pos
            orig_pos = self.press_item_pos
            cand_left = orig_pos.x() + delta.x()
            snapped_left, is_snapped = self._snap_x(cand_left)
            
            if is_snapped:
                snap_pen = QPen(QColor(6, 182, 212, 255), 2.5, Qt.PenStyle.SolidLine)
                self.setPen(snap_pen)
            else:
                pen = QPen(QColor(60, 120, 255, 220), 2.0, Qt.PenStyle.DashLine)
                self.setPen(pen)

            w = self.rect().width()
            h = self.rect().height()
            self.setPos(snapped_left, orig_pos.y())
            self._update_measure_data(snapped_left, orig_pos.y(), w, h, self.pos().x(), w)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        pen = QPen(QColor(60, 120, 255, 220), 2.0, Qt.PenStyle.DashLine)
        self.setPen(pen)
        if self.press_item_pos is not None and self.press_rect is not None:
            w = self.rect().width()
            h = self.rect().height()
            old_bbox = (self.press_item_pos.x(), self.press_item_pos.y(), self.press_item_pos.x() + self.press_rect.width(), self.press_item_pos.y() + self.press_rect.height())
            new_bbox = (self.pos().x(), self.pos().y(), self.pos().x() + w, self.pos().y() + h)
            old_note_coords = getattr(self, 'press_note_coords', [])
            new_note_coords = [(n.id, n.mapped_x, n.mapped_y) for n in self.measure_data.notes if n.mapped_x is not None and n.mapped_y is not None]

            if old_bbox != new_bbox and self.on_moved_callback:
                self.on_moved_callback(self.measure_data, old_bbox, new_bbox, old_note_coords, new_note_coords)
        self.active_handle = None
        self.press_pos = None

    def _update_measure_data(self, x: float, y: float, w: float, h: float, old_x: float, old_w: float):
        self.measure_data.bbox_x1 = float(x)
        self.measure_data.bbox_y1 = float(y)
        self.measure_data.bbox_x2 = float(x + w)
        self.measure_data.bbox_y2 = float(y + h)

        # 마디 이동(좌우 슬라이딩) 또는 가로 폭 변경 시 내부 음표 위치 100% 동기화
        if self.measure_data.notes:
            press_coords = getattr(self, 'press_note_coords', [])
            if old_w > 0 and w != old_w:
                # 가로 폭 조절 (Resize): 비율 비례 확장/축소 (폭주 방지 clamp 적용)
                for note in self.measure_data.notes:
                    orig_x = next((nx for nid, nx, ny in press_coords if nid == note.id), note.mapped_x)
                    if orig_x is not None:
                        ratio = (orig_x - old_x) / old_w
                        ratio = min(max(0.0, ratio), 1.0)
                        note.mapped_x = x + ratio * w
            else:
                # 마디 영역 좌/우 이동 (Move)
                dx = x - old_x
                for note in self.measure_data.notes:
                    orig_x = next((nx for nid, nx, ny in press_coords if nid == note.id), note.mapped_x)
                    if orig_x is not None:
                        note.mapped_x = orig_x + dx

        # 화면 상의 음표 그래픽 점 아이템들도 실시간 위치 동기화
        if self.scene() and self.measure_data.notes:
            views = self.scene().views()
            if views and hasattr(views[0], 'note_items'):
                note_items_map = {ni.note_data.id: ni for ni in views[0].note_items}
                for note in self.measure_data.notes:
                    if note.id in note_items_map and note.mapped_x is not None:
                        ni = note_items_map[note.id]
                        ni.setPos(note.mapped_x, ni.pos().y())

class ScoreGraphicsView(QGraphicsView):
    """PDF 악보 및 MusicXML 오버레이 포인트를 표시하고 상호작용하는 캔버스 뷰어"""
    position_changed = pyqtSignal(float, float)
    action_recorded_signal = pyqtSignal(object)
    add_note_at_signal = pyqtSignal(float, float, str)
    add_measure_at_signal = pyqtSignal(float, float)
    delete_selected_signal = pyqtSignal()
    duplicate_note_signal = pyqtSignal(object)
    delete_single_note_signal = pyqtSignal(object)
    align_measure_notes_signal = pyqtSignal(object)
    delete_measure_signal = pyqtSignal(object)

    recalculate_measure_signal = pyqtSignal(object)
    recalculate_all_signal = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.scene_obj = QGraphicsScene(self)
        self.setScene(self.scene_obj)

        self.pixmap_item: Optional[QGraphicsPixmapItem] = None
        self.measure_items: List[InteractiveMeasureItem] = []
        self.note_items: List[InteractiveNoteItem] = []
        self.snap_barlines_x: List[float] = []
        self.systems: List[Any] = []

        self.show_measures: bool = True
        self.show_notes: bool = True

        # Render quality & Navigation (RubberBandDrag: 마퀴 대각선 영역 선택)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setRubberBandSelectionMode(Qt.ItemSelectionMode.IntersectsItemShape)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)

        self.setStyleSheet("""
            QRubberBand {
                border: 2px dashed #0EA5E9;
                background-color: rgba(14, 165, 233, 0.25);
            }
        """)

        self.zoom_factor: float = 1.05

    def set_systems(self, systems: List[Any]):
        """현재 페이지의 탐지된 악보 시스템(오선지 5줄 정보 포함) 설정"""
        self.systems = systems or []

    def get_pitch_snap_y(self, y_val: float, note_pitch: str = "") -> Tuple[float, str, int]:
        """
        Y 픽셀 좌표로부터 가장 가까운 오선지 줄(Line 1~5) 및 칸(Space 1~4)으로 자석 스냅(Magnet Snap)하고
        역산된 음높이(예: C4, G4, E5) 및 Staff 번호(1: 높은음자리, 2: 낮은음자리)를 반환합니다.
        """
        step_chars = ['C', 'D', 'E', 'F', 'G', 'A', 'B']

        best_sys = None
        if hasattr(self, 'systems') and self.systems:
            min_dist = float('inf')
            for sys in self.systems:
                if sys.y_min - 60 <= y_val <= sys.y_max + 60:
                    best_sys = sys
                    break
                mid_y = (sys.y_min + sys.y_max) / 2.0
                d = abs(y_val - mid_y)
                if d < min_dist:
                    min_dist = d
                    best_sys = sys

        if best_sys and best_sys.treble_staff:
            t_lines = best_sys.treble_staff.y_lines
            b_lines = best_sys.bass_staff.y_lines if best_sys.bass_staff else t_lines
            t_sp = best_sys.treble_staff.line_spacing
            b_sp = best_sys.bass_staff.line_spacing if best_sys.bass_staff else t_sp

            has_bass = best_sys.bass_staff is not None
            split_y = (t_lines[4] + b_lines[0]) / 2.0 if has_bass else (t_lines[4] + 35.0)

            if has_bass and y_val >= split_y:
                staff = 2
                ref_y = float(b_lines[0])
                ref_idx = 26  # A3 (Top line of bass staff)
                step_sp = max(1.0, b_sp / 2.0)
            else:
                staff = 1
                ref_y = float(t_lines[0])
                ref_idx = 38  # F5 (Top line of treble staff)
                step_sp = max(1.0, t_sp / 2.0)
        else:
            staff = 1
            ref_y = 200.0
            ref_idx = 38
            step_sp = 5.0

        diff_steps = round((y_val - ref_y) / step_sp)
        snapped_y = ref_y + (diff_steps * step_sp)

        target_idx = max(0, ref_idx - int(diff_steps))
        octave = target_idx // 7
        step_char = step_chars[target_idx % 7]

        # 기존 임시표(Sharp/Flat) 유지
        acc = ""
        if note_pitch and len(note_pitch) > 1 and note_pitch != "Rest":
            old_step = note_pitch[0].upper()
            if old_step == step_char:
                if '#' in note_pitch: acc = "#"
                elif 'b' in note_pitch: acc = "b"

        pitch_str = f"{step_char}{acc}{octave}"
        return float(snapped_y), pitch_str, staff

    def get_beat_snap_x(self, x_val: float, measure_num: int = -1) -> Tuple[float, float]:
        """
        X 픽셀 좌표로부터 해당 마디 내의 음악적 박자 그리드(1/4박, 1/3박, 1/2박, 1박 등)로 자석 스냅(Magnet Snap)하고
        (스냅된 X 좌표, 계산된 박자 위치)를 반환합니다.
        """
        # 1. 대상 마디 박스(InteractiveMeasureItem) 탐색
        target_m_item = None
        for mi in self.measure_items:
            if measure_num > 0 and mi.measure_data.number == measure_num:
                target_m_item = mi
                break
            elif mi.pos().x() <= x_val <= mi.pos().x() + mi.rect().width():
                target_m_item = mi
                break

        if not target_m_item and self.measure_items:
            target_m_item = min(self.measure_items, key=lambda mi: abs(x_val - (mi.pos().x() + mi.rect().width() * 0.5)))

        if target_m_item:
            m_data = target_m_item.measure_data
            x1 = target_m_item.pos().x()
            width = max(15.0, target_m_item.rect().width())
            total_beats = max(1.0, float(getattr(m_data, 'beats', 4) or 4))

            # 첫 마디 여부 확인
            is_first = (m_data.number == 1)
            left_pad = width * 0.22 if is_first else width * 0.08
            right_pad = width * 0.05
            usable_w = max(10.0, width - left_pad - right_pad)

            # 박자 그리드 후보군 (0.0, 0.25, 0.333, 0.5, 0.667, 0.75, 1.0 ...)
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

            cand_rel_x = x_val - (x1 + left_pad)
            raw_beat = max(0.0, min(total_beats, (cand_rel_x / usable_w) * total_beats))

            # 가장 가까운 박자 후보 탐색
            best_cand = min(candidates, key=lambda c: abs(raw_beat - c))
            snapped_x = (x1 + left_pad) + (best_cand / total_beats) * usable_w

            # 동일 마디 내 다른 음표들의 X좌표(화음 결합용)와도 8px 이내면 자석 스냅
            for ni in self.note_items:
                if ni.note_data.measure_number == m_data.number and abs(ni.pos().x() - x_val) > 0.1:
                    if abs(x_val - ni.pos().x()) <= 8.0:
                        return float(ni.pos().x()), round(best_cand, 3)

            return float(snapped_x), round(best_cand, 3)

        return float(x_val), 0.0

    def set_snap_barlines(self, barlines_x: List[float]):
        """PDF 악보 탐지 세로 마디선 X 좌표 목록 설정"""
        self.snap_barlines_x = barlines_x

    def get_snap_target_xs(self, exclude_measure_num: int = -1) -> List[float]:
        """세로 마디선 및 인접 마디 경계 X 좌표 결합 목록 반환"""
        targets = list(getattr(self, 'snap_barlines_x', []))
        for mi in self.measure_items:
            if mi.measure_data.number != exclude_measure_num:
                targets.append(mi.pos().x())
                targets.append(mi.pos().x() + mi.rect().width())
        return targets

    def set_marquee_mode(self, is_marquee: bool):
        """마퀴 다중 선택 모드(RubberBandDrag)와 캔버스 손바닥 이동 모드(ScrollHandDrag) 전환"""
        if is_marquee:
            self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        else:
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)

    def contextMenuEvent(self, event):
        """우클릭 컨텍스트 메뉴: 마디 정밀 계산, 자동 맞춤, 원하는 위치에 음표/마디 추가, 음표 색상 변경, 복제 및 삭제"""
        pos = event.pos()
        scene_pos = self.mapToScene(pos)
        item = self.itemAt(pos)

        menu = QMenu(self)

        if isinstance(item, InteractiveNoteItem):
            dup_act = menu.addAction("📋 이 음표 점 복제 (Duplicate)")
            menu.addSeparator()
            to_treble = menu.addAction("🟢 높은음자리표 (오른손) 파트로 변경 [녹색]")
            to_bass = menu.addAction("🔵 낮은음자리표 (왼손) 파트로 변경 [파란색]")
            to_rest = menu.addAction("🟡 쉼표 (Rest)로 변경 [노란색]")
            menu.addSeparator()
            recalc_act = menu.addAction("🔬 전체 악보 정밀 계산 (음계/건반/박자 일괄 동기화)")
            delete_act = menu.addAction("🗑️ 이 음표 점 삭제 (Delete)")

            action = menu.exec(self.mapToGlobal(pos))
            if action == dup_act:
                self.duplicate_note_signal.emit(item.note_data)
            elif action == recalc_act:
                self.recalculate_all_signal.emit()
            elif action in (to_treble, to_bass, to_rest):
                old_pitch = item.note_data.pitch
                old_staff = item.note_data.staff
                old_is_rest = item.note_data.is_rest

                if action == to_treble:
                    item.note_data.staff = 1
                    item.note_data.is_rest = False
                    part_desc = "높은음자리 (녹색) 변경"
                elif action == to_bass:
                    item.note_data.staff = 2
                    item.note_data.is_rest = False
                    part_desc = "낮은음자리 (파란색) 변경"
                elif action == to_rest:
                    item.note_data.is_rest = True
                    part_desc = "쉼표 (노란색) 변경"

                self.update_note_item_color(item)
                self.action_recorded_signal.emit(EditAction(
                    action_type="change_note_prop",
                    description=part_desc,
                    measure_num=item.note_data.measure_number,
                    item_id=item.note_data.id,
                    old_pitch=old_pitch, new_pitch=item.note_data.pitch,
                    old_staff=old_staff, new_staff=item.note_data.staff,
                    old_is_rest=old_is_rest, new_is_rest=item.note_data.is_rest
                ))
            elif action == delete_act:
                self.delete_single_note_signal.emit(item.note_data)
            return

        align_m_act = None
        recalc_m_act = None
        del_m_act = None
        if isinstance(item, InteractiveMeasureItem):
            recalc_m_act = menu.addAction(f"🔬 마디 M{item.measure_data.number} 정밀 계산 (음계/건반/박자 동기화)")
            align_m_act = menu.addAction(f"🎯 마디 M{item.measure_data.number} 음표 자동 맞춤 & 새로 채우기")
            del_m_act = menu.addAction(f"🗑️ 마디 M{item.measure_data.number} 영역 삭제")
            menu.addSeparator()

        add_note_act = menu.addAction("➕ 이 위치에 새 음표 점 추가")
        add_measure_act = menu.addAction("➕ 이 위치에 새 마디 영역 추가")
        menu.addSeparator()
        recalc_all_act = menu.addAction("🔬 전체 악보 정밀 계산 (음계/건반/박자 일괄 동기화)")
        menu.addSeparator()
        delete_act = menu.addAction("🗑️ 선택된 음표 점 삭제 (Delete)")

        action = menu.exec(self.mapToGlobal(pos))
        if recalc_m_act and action == recalc_m_act:
            self.recalculate_measure_signal.emit(item.measure_data)
        elif align_m_act and action == align_m_act:
            self.align_measure_notes_signal.emit(item.measure_data)
        elif del_m_act and action == del_m_act:
            self.delete_measure_signal.emit(item.measure_data)
        elif action == recalc_all_act:
            self.recalculate_all_signal.emit()
        elif action == add_note_act:
            pitch, ok = QInputDialog.getText(self, "음표 점 추가", "피치(Pitch)를 입력하세요 (예: C4, G4, E5, Rest):", text="C4")
            if ok and pitch:
                self.add_note_at_signal.emit(scene_pos.x(), scene_pos.y(), pitch.strip())
        elif action == add_measure_act:
            self.add_measure_at_signal.emit(scene_pos.x(), scene_pos.y())
        elif action == delete_act:
            self.delete_selected_signal.emit()

    def update_note_item_color(self, item: InteractiveNoteItem):
        note_data = item.note_data
        midi_num = item._pitch_to_midi(note_data.pitch) if not note_data.is_rest else "N/A"
        if note_data.is_rest:
            color = QColor(255, 180, 0, 220)
            staff_label = "쉼표"
        elif note_data.staff == 2:
            color = QColor(0, 170, 255, 220)
            staff_label = "낮은음자리 (왼손)"
        else:
            color = QColor(0, 210, 110, 220)
            staff_label = "높은음자리 (오른손)"
        item.color = color
        item.setBrush(QBrush(color))
        rx, ry = note_data.mapped_x or 0, note_data.mapped_y or 0
        item.setToolTip(f"M{note_data.measure_number} | 음높이: {note_data.pitch} (🎹 건반 MIDI {midi_num}) | {staff_label} | 좌표: ({int(rx)}, {int(ry)})")

    def set_pdf_pixmap(self, pixmap):
        """PDF 배경 이미지를 캔버스에 세팅합니다."""
        self.scene_obj.clear()
        self.measure_items.clear()
        self.note_items.clear()

        self.pixmap_item = self.scene_obj.addPixmap(pixmap)
        self.pixmap_item.setZValue(0)
        self.scene_obj.setSceneRect(QRectF(pixmap.rect()))

    def display_overlay(self, measures: List[MeasureData], page_index: int):
        """현재 페이지에 해당하는 마디 및 음표 포인트를 캔버스 위에 오버레이합니다."""
        # 기존 오버레이 항목 제거
        for mi in self.measure_items:
            if mi.scene():
                self.scene_obj.removeItem(mi)
        for ni in self.note_items:
            if ni.scene():
                self.scene_obj.removeItem(ni)

        self.measure_items.clear()
        self.note_items.clear()
        if hasattr(self, 'drag_start_map'):
            self.drag_start_map.clear()

        for m in measures:
            if m.mapped_page != page_index:
                continue

            # 마디 바운딩 박스 추가
            if self.show_measures and m.bbox_x1 is not None:
                m_item = InteractiveMeasureItem(m, on_moved_callback=self._on_measure_repositioned)
                m_item.setZValue(10)
                self.scene_obj.addItem(m_item)
                self.measure_items.append(m_item)

            # 음표 점 오버레이 추가
            if self.show_notes:
                for n in m.notes:
                    if n.mapped_page == page_index and n.mapped_x is not None:
                        n_item = InteractiveNoteItem(n, radius=5.5, on_moved_callback=self._on_note_repositioned)
                        n_item.setZValue(20)
                        self.scene_obj.addItem(n_item)
                        self.note_items.append(n_item)

    def set_overlay_visibility(self, show_measures: bool, show_notes: bool):
        self.show_measures = show_measures
        self.show_notes = show_notes
        for mi in self.measure_items:
            mi.setVisible(show_measures)
        for ni in self.note_items:
            ni.setVisible(show_notes)

    def _on_measure_repositioned(self, measure_data: MeasureData, old_bbox: Tuple, new_bbox: Tuple, old_note_coords: List = None, new_note_coords: List = None):
        is_resize = (old_bbox[2] - old_bbox[0]) != (new_bbox[2] - new_bbox[0])
        action = EditAction(
            action_type="resize_measure" if is_resize else "move_measure",
            description=f"마디 M{measure_data.number} {'가로폭 조절' if is_resize else '좌표 이동'}",
            item_id=f"m_{measure_data.number}",
            measure_num=measure_data.number,
            old_bbox=old_bbox,
            new_bbox=new_bbox,
            old_note_coords=old_note_coords,
            new_note_coords=new_note_coords
        )
        self.action_recorded_signal.emit(action)

    def _on_note_repositioned(self, note_data: NoteData, old_x: float, old_y: float, new_x: float, new_y: float):
        action = EditAction(
            action_type="move_note",
            description=f"음표 점 이동 ({note_data.pitch})",
            item_id=note_data.id,
            measure_num=note_data.measure_number,
            old_x=old_x, old_y=old_y,
            new_x=new_x, new_y=new_y
        )
        self.action_recorded_signal.emit(action)

    def zoom_in(self):
        self.scale(1.2, 1.2)

    def zoom_out(self):
        self.scale(1.0 / 1.2, 1.0 / 1.2)

    def zoom_fit_page(self):
        if self.pixmap_item:
            self.fitInView(self.pixmap_item, Qt.AspectRatioMode.KeepAspectRatio)

    def wheelEvent(self, event):
        """Ctrl + 마우스 휠을 통한 확장 줌 인/아웃"""
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            if event.angleDelta().y() > 0:
                self.scale(self.zoom_factor, self.zoom_factor)
            else:
                self.scale(1.0 / self.zoom_factor, 1.0 / self.zoom_factor)
        else:
            super().wheelEvent(event)

    def keyPressEvent(self, event):
        """Space 키 누름 시 캔버스 이동, 방향키 시 음계 줄/칸 스냅 이동, Delete 키 시 삭제"""
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            event.accept()
            return

        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.delete_selected_signal.emit()
            event.accept()
            return

        if event.modifiers() == Qt.KeyboardModifier.ControlModifier and event.key() == Qt.Key.Key_D:
            selected_notes = [i for i in self.scene_obj.selectedItems() if isinstance(i, InteractiveNoteItem)]
            if selected_notes:
                self.duplicate_note_signal.emit(selected_notes[0].note_data)
            event.accept()
            return

        # 선택된 음표 점 ↑ / ↓ 방향키 수직 음계 스냅 이동
        if event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            selected_notes = [i for i in self.scene_obj.selectedItems() if isinstance(i, InteractiveNoteItem)]
            if selected_notes:
                direction = -1 if event.key() == Qt.Key.Key_Up else 1
                moved_actions = []
                for ni in selected_notes:
                    old_x, old_y = ni.pos().x(), ni.pos().y()
                    old_pitch = ni.note_data.pitch
                    # 1 pitch step move (~5.0px)
                    cand_y = old_y + direction * 5.0
                    snapped_y, pitch_str, staff = self.get_pitch_snap_y(cand_y, ni.note_data.pitch)
                    ni.setPos(old_x, snapped_y)
                    ni.note_data.mapped_x = old_x
                    ni.note_data.mapped_y = snapped_y
                    ni.note_data.pitch = pitch_str
                    ni.note_data.staff = staff
                    ni.update_appearance()

                    moved_actions.append(EditAction(
                        action_type="move_note",
                        description=f"음표 음계 이동 ({old_pitch} → {pitch_str})",
                        item_id=ni.note_data.id,
                        measure_num=ni.note_data.measure_number,
                        note_data=ni.note_data,
                        old_x=old_x, old_y=old_y,
                        new_x=old_x, new_y=snapped_y
                    ))
                if len(moved_actions) == 1:
                    self.action_recorded_signal.emit(moved_actions[0])
                elif len(moved_actions) > 1:
                    self.action_recorded_signal.emit(GroupAction(description=f"{len(moved_actions)}개 음표 음계 수직 이동", actions=moved_actions))
                event.accept()
                return

        # 선택된 음표 점 ← / → 방향키 수평 이동
        if event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            selected_notes = [i for i in self.scene_obj.selectedItems() if isinstance(i, InteractiveNoteItem)]
            if selected_notes:
                if event.key() == Qt.Key.Key_Left:
                    dx = -1.0 if (event.modifiers() & Qt.KeyboardModifier.ShiftModifier) else -3.0
                else:
                    dx = 1.0 if (event.modifiers() & Qt.KeyboardModifier.ShiftModifier) else 3.0
                for ni in selected_notes:
                    ni.setPos(ni.pos().x() + dx, ni.pos().y())
                    ni.note_data.mapped_x = float(ni.pos().x())
                    ni.note_data.mapped_y = float(ni.pos().y())
                    ni.update_appearance()
                event.accept()
                return

        if event.modifiers() == Qt.KeyboardModifier.ShiftModifier:
            selected_items = self.scene_obj.selectedItems()
            if selected_items:
                dx, dy = 0.0, 0.0
                if event.key() == Qt.Key.Key_Left: dx = -1.0
                elif event.key() == Qt.Key.Key_Right: dx = 1.0
                elif event.key() == Qt.Key.Key_Up: dy = -1.0
                elif event.key() == Qt.Key.Key_Down: dy = 1.0

                if dx != 0.0 or dy != 0.0:
                    for item in selected_items:
                        item.setPos(item.pos().x() + dx, item.pos().y() + dy)
                        if isinstance(item, InteractiveNoteItem):
                            item.note_data.mapped_x = float(item.pos().x())
                            item.note_data.mapped_y = float(item.pos().y())
                            item.update_appearance()
                        elif isinstance(item, InteractiveMeasureItem):
                            w = item.rect().width()
                            h = item.rect().height()
                            item.measure_data.bbox_x1 = float(item.pos().x())
                            item.measure_data.bbox_y1 = float(item.pos().y())
                            item.measure_data.bbox_x2 = float(item.pos().x() + w)
                            item.measure_data.bbox_y2 = float(item.pos().y() + h)
                    event.accept()
                    return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        """Space 키 떼면 마퀴 대각선 선택 모드로 원복"""
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
            event.accept()
            return
        super().keyReleaseEvent(event)

    def mousePressEvent(self, event):
        self.drag_start_map = {}
        if event.button() == Qt.MouseButton.LeftButton:
            for item in self.scene_obj.selectedItems():
                if isinstance(item, (InteractiveNoteItem, InteractiveMeasureItem)):
                    self.drag_start_map[item] = QPointF(item.pos())
                    if isinstance(item, InteractiveNoteItem):
                        item.press_pos = QPointF(item.pos())

            item_under_mouse = self.itemAt(event.pos())
            if isinstance(item_under_mouse, InteractiveNoteItem):
                item_under_mouse.press_pos = QPointF(item_under_mouse.pos())
                if item_under_mouse not in self.drag_start_map:
                    self.drag_start_map[item_under_mouse] = QPointF(item_under_mouse.pos())

        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if hasattr(self, 'drag_start_map') and self.drag_start_map:
            moved_actions = []
            for item, old_pos in list(self.drag_start_map.items()):
                try:
                    if item and item.scene() is not None:
                        cur_pos = item.pos()
                        if cur_pos.x() != old_pos.x() or cur_pos.y() != old_pos.y():
                            if isinstance(item, InteractiveNoteItem):
                                moved_actions.append(EditAction(
                                    action_type="move_note",
                                    description=f"음표 이동 ({item.note_data.pitch})",
                                    item_id=item.note_data.id,
                                    measure_num=item.note_data.measure_number,
                                    note_data=item.note_data,
                                    old_x=old_pos.x(), old_y=old_pos.y(),
                                    new_x=cur_pos.x(), new_y=cur_pos.y()
                                ))
                            elif isinstance(item, InteractiveMeasureItem):
                                w = item.rect().width()
                                h = item.rect().height()
                                old_bbox = (old_pos.x(), old_pos.y(), old_pos.x() + w, old_pos.y() + h)
                                new_bbox = (cur_pos.x(), cur_pos.y(), cur_pos.x() + w, cur_pos.y() + h)
                                moved_actions.append(EditAction(
                                    action_type="move_measure",
                                    description=f"마디 M{item.measure_data.number} 이동",
                                    item_id=f"m_{item.measure_data.number}",
                                    measure_num=item.measure_data.number,
                                    old_bbox=old_bbox, new_bbox=new_bbox
                                ))
                except (RuntimeError, ReferenceError, AttributeError):
                    pass

            if len(moved_actions) == 1:
                self.action_recorded_signal.emit(moved_actions[0])
            elif len(moved_actions) > 1:
                group_desc = f"{len(moved_actions)}개 선택 항목 일괄 이동"
                self.action_recorded_signal.emit(GroupAction(description=group_desc, actions=moved_actions))

            for item in list(self.drag_start_map.keys()):
                try:
                    if isinstance(item, InteractiveNoteItem):
                        item.press_pos = None
                except (RuntimeError, ReferenceError, AttributeError):
                    pass

            self.drag_start_map.clear()

    def mouseMoveEvent(self, event):
        scene_pos = self.mapToScene(event.pos())
        self.position_changed.emit(scene_pos.x(), scene_pos.y())
        super().mouseMoveEvent(event)
