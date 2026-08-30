import os
from core.musicxml_parser import MusicXMLParser
from core.musicxml_exporter import MusicXMLExporter

parser = MusicXMLParser()
exporter = MusicXMLExporter()

# 1. Load 01.musicxml
score = parser.parse("c:/Users/DiCiA/PycharmProjects/NoteFlow Studio-Program/Save/01.musicxml")
parser.distribute_measures_across_pages(score, 2, 200, None)

# 2. Simulate User Dragging M3's left border to the left by 50px
m3 = next((m for m in score.measures if m.number == 3), None)
old_x1 = m3.bbox_x1
m3.bbox_x1 -= 50
print(f"M3 bbox_x1 changed from {old_x1} to {m3.bbox_x1}")

# 3. Export to 03.musicxml
out_path = "c:/Users/DiCiA/PycharmProjects/NoteFlow Studio-Program/Save/test_03.musicxml"
exporter.export_musicxml(score, out_path)

# 4. Reload test_03.musicxml
score2 = parser.parse(out_path)
parser.distribute_measures_across_pages(score2, 2, 200, None)
m3_reloaded = next((m for m in score2.measures if m.number == 3), None)
print(f"Reloaded M3 bbox_x1 is {m3_reloaded.bbox_x1}")

if m3_reloaded.bbox_x1 == m3.bbox_x1:
    print("SUCCESS: coordinates persisted perfectly.")
else:
    print("FAILED: coordinates reverted.")
