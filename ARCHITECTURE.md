# 🎼 NoteFlow Studio - 프로젝트 구성도 & 파이프라인 구조도

NoteFlow Studio는 **PDF 악보 이미지**와 **MusicXML 디지털 악보 데이터**를 컴퓨터 비전(OpenCV)과 지능형 악보 레이아웃 분석 알고리즘을 통해 **서브픽셀 단위(100% 정밀도)로 자동 동기화(Sync & Auto-Align)**하고 인터랙티브하게 편집·저장할 수 있는 차세대 악보 제작 및 맵핑 오버레이 툴입니다.

---

## 1. 🏗️ 전체 프로젝트 아키텍처 (Project Architecture)

`mermaid
graph TD
    subgraph UI_Layer [🖥️ 사용자 인터페이스 계층 (UI Layer - PyQt6)]
        MW[MainWindow - 메인 윈도우 & 툴바]
        GV[GraphicsView & CanvasView - 대화형 캔버스]
        CP[ControlPanel - 8단계 워크플로우 컨트롤 패널]
        UM[UndoManager - 실행 취소 / 다시 실행]
        Items[Interactive Items - 마디/음표/쉼표/조절점 UI 오버레이]
    end

    subgraph Core_Engine [⚙️ 코어 엔진 계층 (Core Processing Layer)]
        PR[PDFRenderer - PyMuPDF 기반 초고해상도 PDF 래스터라이저]
        MP[MusicXMLParser - MusicXML 파서 & 악보 구조화 모델]
        AA[AutoAligner - AI 악보 자동 싱크 및 서브픽셀 타원 피팅]
        EX[MusicXMLExporter - 보정보표 MusicXML 영속성 저장기]
    end

    subgraph Vision_Utils [👁️ 컴퓨터 비전 및 레이아웃 분석 (Vision & Layout Detector)]
        SLD[SheetLayoutDetector - 오선지 시스템 및 세로 마디선 인식]
        HPS[Horizontal Projection - 대보표 Grand Staff 감지]
        VPS[Vertical Projection - 세로 마디선 Barline 분할]
        EL[Ellipse Fitting & Contour Analysis - 타원 음표 머리 추출]
    end

    subgraph Data_Model [💾 데이터 모델 (Data Structures)]
        PS[ParsedScore - 악보 전체 메타데이터]
        MD[MeasureData - 마디 단위 구조체 Bounding Box]
        ND[NoteData - 음표/쉼표 서브픽셀 좌표 및 음계/파트]
        SR[SystemRegion & StaffInfo - 오선지 줄/칸 픽셀 위치]
    end

    %% 연결 관계
    MW --> GV
    MW --> CP
    MW --> UM
    GV --> Items

    CP --> PR
    CP --> MP
    CP --> AA
    CP --> EX

    AA --> SLD
    AA --> PR
    AA --> MP
    SLD --> HPS
    SLD --> VPS
    SLD --> EL

    MP --> PS
    PS --> MD
    MD --> ND
    SLD --> SR
`

---

## 2. 🔄 데이터 처리 파이프라인 구조도 (Data Processing Pipeline)

`mermaid
sequenceDiagram
    autonumber
    actor User as 👤 사용자
    participant UI as 🖥️ UI (MainWindow / Canvas)
    participant PDF as 📄 PDFRenderer (PyMuPDF)
    participant XML as 🎼 MusicXMLParser
    participant Vision as 👁️ SheetLayoutDetector
    participant Aligner as ⚡ AutoAligner
    participant Export as 💾 MusicXMLExporter

    User->>UI: 1. PDF 악보 & MusicXML 로드
    UI->>PDF: render_page_pixmap(dpi=200)
    UI->>XML: parse(musicxml_path)
    PDF-->>UI: BGR Image & QPixmap 전달
    XML-->>UI: ParsedScore (Measure / Note 객체) 전달

    User->>UI: 2. [싱크 맞추기 (Auto-Align)] 클릭 (전체 또는 마퀴 선택 영역)
    UI->>Aligner: align_selected_notes_to_noteheads(selected_notes, page_idx, score)
    
    Aligner->>Vision: detect_staff_lines_and_systems(bgr_img)
    Vision-->>Aligner: 5줄 오선지 Y좌표 & Grand Staff System 정보 반환
    
    Note over Aligner: [컴퓨터 비전 타원 추출]<br/>1. Otsu 이진화 & 타원형 열림 모폴로지<br/>2. 2도 대각선 화음 분할 (MA >= 30, angle 35~85°)<br/>3. 수직 화음 분할 (height >= 25, area >= 300)<br/>4. 클레프(𝄞/𝄢) 및 부점(Dot) 100% 원천 배제
    
    Note over Aligner: [파트별 전역 최적 1:1 매칭]<br/>1. 높은음자리(Staff 1) vs 낮은음자리(Staff 2) 분리<br/>2. 단조 증가 순서(Monotonic X-Order) 최적 조합<br/>3. 음표 부족 시 실시간 NoteData 자동 생성(Auto-Create)
    
    Aligner-->>UI: 검출 타원 정중앙(X, Y) 100% 대입 및 신규 음표 생성 완료
    UI->>UI: render_current_page() (초록/파랑 음표 점 씬 렌더링)
    
    User->>UI: 3. [보정 파일 저장] 클릭
    UI->>Export: export_modified_musicxml(score, save_path)
    Export-->>User: PDF 서브픽셀 좌표가 완벽 보존된 MusicXML 파일 출력
`

---

## 3. 📂 디렉토리 및 모듈 구성 (Directory Structure)

`
NoteFlow Studio-Program/
├── core/                           # ⚙️ 핵심 엔진 모듈
│   ├── auto_aligner.py             # 지능형 타원 음표 머리 서브픽셀 정밀 싱크 & 자동 생성 엔진
│   ├── musicxml_parser.py          # MusicXML 파서 및 악보 데이터 구조체
│   ├── musicxml_exporter.py        # 맵핑 좌표 보존 MusicXML 영속성 저장기
│   ├── pdf_renderer.py             # PyMuPDF 기반 200 DPI PDF 래스터라이저
│   └── undo_manager.py             # 명령 취소(Undo) / 다시 실행(Redo) 스택 관리자
│
├── utils/                          # 👁️ 컴퓨터 비전 및 레이아웃 유틸리티
│   └── layout_detector.py          # 오선지 5선 탐지, 대보표 시스템 분할, 세로 마디선 인식
│
├── ui/                             # 🖥️ PyQt6 기반 사용자 인터페이스
│   ├── main_window.py              # 메인 윈도우, 메뉴바, 툴바, 싱크 이벤트 핸들러
│   ├── graphics_view.py            # 대화형 그래픽 뷰, 마퀴(RubberBand) 선택, 자석 스냅
│   ├── control_panel.py            # 8단계 작업 흐름 우측 컨트롤 패널
│   ├── interactive_items.py        # 마디 박스(InteractiveMeasureItem), 음표 점(InteractiveNoteItem)
│   └── progress_dialog.py          # 싱크 진행률 모달 프로그레스 다이얼로그
│
├── tests/                          # 🧪 단위 테스트 및 검증 스위트
│   ├── test_auto_aligner.py        # 자동 싱크 알고리즘 단위 테스트
│   ├── test_musicxml_parser.py     # XML 파싱 검증 테스트
│   └── test_pdf_renderer.py        # PDF 렌더링 검증 테스트
│
├── Save/                           # 💾 보정 완료 MusicXML 및 프로젝트 저장소
├── Input-Green Breeze Picnic/      # 📄 테스트용 샘플 악보 (PDF / MusicXML)
├── main.py                         # 🚀 프로그램 진입점 (Entry Point)
├── ARCHITECTURE.md                 # 🏗️ 시스템 아키텍처 및 파이프라인 문서
├── 오류_처리와_처리_결과.md        # 📋 오류 분석 및 해결 결과 보고서
└── requirements.txt                # 📦 필수 라이브러리 목록 (PyQt6, opencv-python, PyMuPDF 등)
`
