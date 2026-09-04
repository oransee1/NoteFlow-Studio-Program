import sys
import os
import traceback
from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtCore import Qt
from ui.main_window import MainWindow

def exception_hook(exctype, value, tb):
    """Qt 내부 이벤트 루프나 슬롯에서 발생하는 미처리 예외를 가로채어 충돌(0xC0000409) 방지 및 상세 로그 출력"""
    err_msg = "".join(traceback.format_exception(exctype, value, tb))
    print(err_msg, file=sys.stderr)
    try:
        QMessageBox.critical(None, "오류 발생 (Error)", f"프로그램 실행 중 예외가 발생했습니다:\n\n{err_msg}")
    except Exception:
        pass


def main():
    # High-DPI 및 소프트웨어 렌더러 안전 환경 변수 (GPU 드라이버 충돌 및 멈춤 방지)
    os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"
    os.environ["QSG_RHI_PREFER_SOFTWARE_RENDERER"] = "1"
    os.environ["QT_LOGGING_RULES"] = "*.debug=false;qt.qpa.*=false;qt.text.*=false"
    sys.excepthook = exception_hook
    
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # 글로벌 애플리케이션 스타일시트 (모던 딥 메탈릭 룩)
    app.setStyleSheet("""
        QMainWindow {
            background-color: #F8FAFC;
        }
        QGraphicsView {
            background-color: #0F172A;
            border: none;
        }
        QToolTip {
            background-color: #1E293B;
            color: #F8FAFC;
            border: 1px solid #475569;
            padding: 4px 8px;
            font-size: 12px;
            border-radius: 4px;
        }
        QStatusBar {
            background-color: #F1F5F9;
            color: #334155;
            font-weight: bold;
        }
    """)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())

if __name__ == "__main__":
    main()

