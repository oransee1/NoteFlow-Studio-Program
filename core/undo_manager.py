import copy
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Any

@dataclass
class MoveAction:
    """하위 호환성을 위해 유지되는 액션 클래스"""
    action_type: str  # "note" or "measure"
    item_id: str
    measure_num: int
    old_x: float
    old_y: float
    new_x: float
    new_y: float
    old_bbox: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    new_bbox: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    description: str = ""

@dataclass
class EditAction:
    """단일 편집 작업 데이터 모델"""
    action_type: str
    description: str
    measure_num: int = 0
    item_id: str = ""
    page_index: int = 0
    old_x: Optional[float] = None
    old_y: Optional[float] = None
    new_x: Optional[float] = None
    new_y: Optional[float] = None
    old_bbox: Optional[Tuple[float, float, float, float]] = None
    new_bbox: Optional[Tuple[float, float, float, float]] = None
    note_data: Optional[Any] = None
    measure_data: Optional[Any] = None
    old_pitch: Optional[str] = None
    new_pitch: Optional[str] = None
    old_staff: Optional[int] = None
    new_staff: Optional[int] = None
    old_is_rest: Optional[bool] = None
    new_is_rest: Optional[bool] = None
    old_note_coords: Optional[List[Tuple[str, float, float]]] = None
    new_note_coords: Optional[List[Tuple[str, float, float]]] = None

@dataclass
class GroupAction:
    """그룹 액션 데이터 모델"""
    description: str
    actions: List[Any] = field(default_factory=list)

@dataclass
class ScoreSnapshot:
    """전체 악보 마디 및 음표 2D 좌표 상태 딥카피 스냅샷 클래스 (음표 유실 100% 원천 차단)"""
    description: str
    measures: List[Any]

class UndoManager:
    def __init__(self, max_history: int = 100):
        self.max_history = max_history
        self.undo_stack: List[ScoreSnapshot] = []
        self.redo_stack: List[ScoreSnapshot] = []

    def push_snapshot(self, score: Any, description: str):
        """편집 작업 전 현재 악보 전체 마디 및 음표 2D 좌표 상태를 딥카피 스냅샷으로 임시 저장합니다."""
        if not score or score.measures is None:
            return
        snapshot = ScoreSnapshot(
            description=description,
            measures=copy.deepcopy(score.measures)
        )
        self.undo_stack.append(snapshot)
        if len(self.undo_stack) > self.max_history:
            self.undo_stack.pop(0)
        self.redo_stack.clear()

    def push_action(self, action: Any, score: Any = None):
        """하위 호환성 push_action: score가 전달되면 스냅샷을 푸시하고, 아니면 단일 액션을 푸시합니다."""
        desc = getattr(action, 'description', '편집 작업')
        if score and hasattr(score, 'measures') and score.measures is not None:
            self.push_snapshot(score, desc)
        else:
            self.undo_stack.append(ScoreSnapshot(description=desc, measures=[action]))
            self.redo_stack.clear()

    @property
    def can_undo(self) -> bool:
        return len(self.undo_stack) > 0

    @property
    def can_redo(self) -> bool:
        return len(self.redo_stack) > 0

    def undo(self, score: Any) -> Optional[str]:
        """Ctrl+Z: 이전 단계의 전체 마디 및 음표 점 좌표 스냅샷(또는 액션)을 100% 완전 복원합니다."""
        if not self.undo_stack or not score:
            return None

        prev_snapshot = self.undo_stack.pop()

        if isinstance(prev_snapshot.measures, list) and prev_snapshot.measures and hasattr(prev_snapshot.measures[0], 'number'):
            # 전체 스냅샷 모드 (임시 저장 공간 딥카피 복원)
            current_snapshot = ScoreSnapshot(
                description="현재 상태",
                measures=copy.deepcopy(score.measures)
            )
            self.redo_stack.append(current_snapshot)
            score.measures = copy.deepcopy(prev_snapshot.measures)
            score.total_measures = len(score.measures)
        else:
            # 단일/그룹 액션 모드 (하위 호환성)
            self.redo_stack.append(prev_snapshot)
            act_obj = prev_snapshot.measures[0] if isinstance(prev_snapshot.measures, list) and prev_snapshot.measures else prev_snapshot.measures
            if isinstance(act_obj, GroupAction):
                for a in reversed(act_obj.actions):
                    self._apply_single_action(score, a, is_undo=True)
            else:
                self._apply_single_action(score, act_obj, is_undo=True)

        return prev_snapshot.description

    def redo(self, score: Any) -> Optional[str]:
        """Ctrl+Y: 취소한 단계의 전체 마디 및 음표 점 좌표 스냅샷(또는 액션)을 재복원합니다."""
        if not self.redo_stack or not score:
            return None

        next_snapshot = self.redo_stack.pop()

        if isinstance(next_snapshot.measures, list) and next_snapshot.measures and hasattr(next_snapshot.measures[0], 'number'):
            # 전체 스냅샷 모드
            current_snapshot = ScoreSnapshot(
                description="현재 상태",
                measures=copy.deepcopy(score.measures)
            )
            self.undo_stack.append(current_snapshot)
            score.measures = copy.deepcopy(next_snapshot.measures)
            score.total_measures = len(score.measures)
        else:
            # 단일/그룹 액션 모드
            self.undo_stack.append(next_snapshot)
            act_obj = next_snapshot.measures[0] if isinstance(next_snapshot.measures, list) and next_snapshot.measures else next_snapshot.measures
            if isinstance(act_obj, GroupAction):
                for a in act_obj.actions:
                    self._apply_single_action(score, a, is_undo=False)
            else:
                self._apply_single_action(score, act_obj, is_undo=False)

        return next_snapshot.description

    def clear(self):
        self.undo_stack.clear()
        self.redo_stack.clear()

    def _apply_single_action(self, score, action: Any, is_undo: bool):
        if not score or not score.measures:
            return

        # 하위 호환성 MoveAction 지원
        if isinstance(action, MoveAction):
            m_data = next((m for m in score.measures if m.number == action.measure_num), None)
            if not m_data: return
            if action.action_type == "note":
                note = next((n for n in m_data.notes if n.id == action.item_id), None)
                if note:
                    note.mapped_x = action.old_x if is_undo else action.new_x
                    note.mapped_y = action.old_y if is_undo else action.new_y
            elif action.action_type == "measure":
                target_bbox = action.old_bbox if is_undo else action.new_bbox
                m_data.bbox_x1, m_data.bbox_y1, m_data.bbox_x2, m_data.bbox_y2 = target_bbox
            return

        # 신규 종합 EditAction 지원
        act_type = action.action_type
        m_data = next((m for m in score.measures if m.number == action.measure_num), None)

        if act_type == "move_note":
            note = action.note_data
            if not note and m_data:
                note = next((n for n in m_data.notes if n.id == action.item_id), None)
            if not note:
                for m in score.measures:
                    note = next((n for n in m.notes if n.id == action.item_id), None)
                    if note: break
            if note:
                note.mapped_x = action.old_x if is_undo else action.new_x
                note.mapped_y = action.old_y if is_undo else action.new_y

        elif act_type in ("move_measure", "resize_measure") and m_data:
            target_bbox = action.old_bbox if is_undo else action.new_bbox
            if target_bbox:
                m_data.bbox_x1, m_data.bbox_y1, m_data.bbox_x2, m_data.bbox_y2 = target_bbox
            
            note_coords = action.old_note_coords if is_undo else action.new_note_coords
            if note_coords:
                coord_map = {n_id: (nx, ny) for n_id, nx, ny in note_coords}
                for note in m_data.notes:
                    if note.id in coord_map:
                        note.mapped_x, note.mapped_y = coord_map[note.id]

        elif act_type in ("add_note", "duplicate_note") and action.note_data:
            target_m = m_data or next((m for m in score.measures if m.number == action.note_data.measure_number), None)
            if target_m:
                if is_undo:
                    if action.note_data in target_m.notes:
                        target_m.notes.remove(action.note_data)
                    else:
                        target_m.notes = [n for n in target_m.notes if n is not action.note_data and n.id != action.note_data.id]
                else:
                    if action.note_data not in target_m.notes:
                        target_m.notes.append(action.note_data)

        elif act_type == "delete_note" and action.note_data:
            target_m = m_data or next((m for m in score.measures if m.number == action.note_data.measure_number), None)
            if target_m:
                if is_undo:
                    if action.note_data not in target_m.notes:
                        target_m.notes.append(action.note_data)
                else:
                    if action.note_data in target_m.notes:
                        target_m.notes.remove(action.note_data)
                    else:
                        target_m.notes = [n for n in target_m.notes if n is not action.note_data and n.id != action.note_data.id]

        elif act_type == "add_measure" and action.measure_data:
            if is_undo:
                score.measures = [m for m in score.measures if m.number != action.measure_data.number]
            else:
                if action.measure_data not in score.measures:
                    score.measures.append(action.measure_data)
            score.total_measures = len(score.measures)

        elif act_type == "delete_measure" and action.measure_data:
            if is_undo:
                if action.measure_data not in score.measures:
                    score.measures.append(action.measure_data)
                    score.measures.sort(key=lambda m: m.number)
            else:
                score.measures = [m for m in score.measures if m.number != action.measure_data.number]
            score.total_measures = len(score.measures)

        elif act_type == "change_note_prop":
            note = None
            if m_data:
                note = next((n for n in m_data.notes if n.id == action.item_id), None)
            if not note:
                for m in score.measures:
                    note = next((n for n in m.notes if n.id == action.item_id), None)
                    if note: break
            if note:
                note.pitch = action.old_pitch if is_undo else action.new_pitch
                note.staff = action.old_staff if is_undo else action.new_staff
                note.is_rest = action.old_is_rest if is_undo else action.new_is_rest

        elif act_type == "offset_page":
            dx = -(action.old_x or 0.0) if is_undo else (action.old_x or 0.0)
            dy = -(action.old_y or 0.0) if is_undo else (action.old_y or 0.0)
            for m in score.measures:
                if m.mapped_page == action.page_index:
                    if m.bbox_x1 is not None: m.bbox_x1 += dx
                    if m.bbox_x2 is not None: m.bbox_x2 += dx
                    if m.bbox_y1 is not None: m.bbox_y1 += dy
                    if m.bbox_y2 is not None: m.bbox_y2 += dy
                    for n in m.notes:
                        if n.mapped_x is not None: n.mapped_x += dx
                        if n.mapped_y is not None: n.mapped_y += dy
