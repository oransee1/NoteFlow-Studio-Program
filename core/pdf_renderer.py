import pymupdf as fitz  # PyMuPDF
import numpy as np
from PyQt6.QtGui import QImage, QPixmap
from typing import Tuple, List, Optional

class PDFRenderer:
    def __init__(self):
        self.doc: Optional[fitz.Document] = None
        self.pdf_path: str = ""
        self.dpi: int = 200

    def load_pdf(self, path: str) -> int:
        """PDF 파일을 로드하고 총 페이지 수를 반올림하여 반환합니다."""
        self.pdf_path = path
        self.doc = fitz.open(path)
        return len(self.doc)

    @property
    def page_count(self) -> int:
        return len(self.doc) if self.doc else 0

    def get_page_size(self, page_index: int) -> Tuple[float, float]:
        """페이지의 포인트 단위 (width, height)를 반환합니다."""
        if not self.doc or page_index < 0 or page_index >= len(self.doc):
            return (0.0, 0.0)
        page = self.doc[page_index]
        rect = page.rect
        return (rect.width, rect.height)

    def render_page_pixmap(self, page_index: int, dpi: int = 200) -> Tuple[QPixmap, np.ndarray, float]:
        """
        지정한 페이지를 QPixmap 및 OpenCV용 BGR NumPy 이미지로 렌더링합니다.
        반환값: (QPixmap, bgr_numpy_array, zoom_scale)
        """
        if not self.doc or page_index < 0 or page_index >= len(self.doc):
            raise ValueError(f"유효하지 않은 페이지 인덱스입니다: {page_index}")

        page = self.doc[page_index]
        zoom = dpi / 72.0  # 72 DPI가 기본 포인트 기준
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)

        # PyMuPDF pixmap 데이터를 NumPy 배열로 변환
        # pix.samples는 bytes (RGB)
        img_np = np.frombuffer(pix.samples, dtype=np.uint8).reshape((pix.height, pix.width, 3))
        
        # OpenCV BGR 이미지 생성
        import cv2
        img_bgr = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)

        # PyQt QImage 및 QPixmap 생성
        qimg = QImage(
            pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888
        )
        qpixmap = QPixmap.fromImage(qimg)

        return qpixmap, img_bgr, zoom

    def close(self):
        if self.doc:
            self.doc.close()
            self.doc = None
