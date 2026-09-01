# 🎼 NoteFlow Studio (악보 싱크 및 맵핑 오버레이 툴)

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![PyQt6](https://img.shields.io/badge/GUI-PyQt6-green.svg)](https://pypi.org/project/PyQt6/)
[![OpenCV](https://img.shields.io/badge/Vision-OpenCV-red.svg)](https://opencv.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**NoteFlow Studio**는 **PDF 악보 이미지**와 **MusicXML 디지털 악보 데이터**를 컴퓨터 비전(OpenCV)과 지능형 악보 레이아웃 분석 알고리즘을 통해 **서브픽셀 단위(100% 정밀도)로 자동 동기화(Sync & Auto-Align)**하고 인터랙티브하게 편집·저장할 수 있는 차세대 악보 제작 및 맵핑 오버레이 데스크톱 애플리케이션입니다.

---

## 📚 관련 문서 바로가기
- 🏗️ **[시스템 아키텍처 및 파이프라인 구조도 (ARCHITECTURE.md)](ARCHITECTURE.md)**
- 📋 **[오류 분석, 처리 과정 및 최종 결과 보고서 (오류_처리와_처리_결과.md)](오류_처리와_처리_결과.md)**

---

## ✨ 핵심 기능 (Key Features)

1. **📄 초고해상도 PDF 악보 래스터라이징 & 줌/패닝**
   - PyMuPDF 기반 200 DPI 서브픽셀 정밀 렌더링
   - Space+드래그(화면 이동), 마우스 휠(초정밀 확대/축소), 마퀴(RubberBand) 다중 영역 선택

2. **⚡ 지능형 AI 자동 싱크 & 서브픽셀 타원 피팅 (Auto-Align)**
   - **타원 음표 머리 서브픽셀 피팅**: Otsu 이진화 & 타원형 열림 모폴로지 기반 정중앙 좌표 검출
   - **수직 및 2도 대각선 화음 분할**: 밀착된 화음 음표 머리를 개별 타원으로 100% 자동 분리
   - **부족 음표 실시간 자동 생성 (Auto-Create)**: 음표점이 부족할 때 해당 타원 위치에 NoteData 즉시 생성
   - **악보 잡음 100% 원천 배제**: 클레프(𝄞/𝄢), 박자표(2/4), 부점(Dot), 가사/코드 텍스트 완벽 분리

3. **🎨 파트별 색상 및 오선지 자석 스냅 (Magnetic Snap)**
   - 🟢 높은음자리표(오른손): 연두색 음표 점
   - 🔵 낮은음자리표(왼손): 파란색 음표 점
   - 🟡 쉼표(Rest): 노란색 점
   - 5줄 오선지 줄/칸 높이에 착 달라붙는 스마트 자석 스냅 & 음계(Pitch)/MIDI 건반 자동 갱신

4. **💾 완벽한 데이터 영속성 (MusicXML Export & Persistence)**
   - 보정된 서브픽셀 X, Y 좌표 메타데이터가 100% 무손실 반영된 MusicXML 내보내기/저장
   - 무제한 실행 취소 / 다시 실행 (Undo / Redo) 지원

---

## 🚀 설치 및 실행 방법

### 1. 요구 사항
- Python 3.10 이상

### 2. 패키지 설치
`ash
pip install -r requirements.txt
`

### 3. 프로그램 실행
`ash
python main.py
`
*또는 un.bat 파일을 더블 클릭하여 바로 실행할 수 있습니다.*

---

## 🧪 테스트 스위트 실행

`ash
# 단위 테스트 실행 (6개 테스트 전원 통과)
python -m unittest discover tests

# 데이터 영속성 무손실 검증 테스트
python test_persistence.py
`
