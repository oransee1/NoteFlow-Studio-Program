import sys
import os
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from ui.main_window import MainWindow

def main():
    # High-DPI 지원 활성화
    os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
    
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
