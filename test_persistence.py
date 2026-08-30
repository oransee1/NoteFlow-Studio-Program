import os
import sys

# Add workspace to path
sys.path.append(r"c:\Users\DiCiA\PycharmProjects\NoteFlow Studio-Program")

from core.musicxml_parser import MusicXMLParser
from core.musicxml_exporter import MusicXMLExporter

def test_save_load():
    parser = MusicXMLParser()
    exporter = MusicXMLExporter()
    
    # Check if Save/01.musicxml exists
    test_file = r"c:\Users\DiCiA\PycharmProjects\NoteFlow Studio-Program\Save\01.musicxml"
    if not os.path.exists(test_file):
        print(f"Test file not found: {test_file}")
        # Use whatever xml we have, or exit
        return
        
    print("1. Parsing original file...")
    score1 = parser.parse(test_file)
    print(f"Loaded {len(score1.measures)} measures.")
    
    # 2. Modify a coordinate (simulation of user interaction)
    m1 = score1.measures[0]
    n1 = m1.notes[0]
    original_x = n1.mapped_x or 0
    new_x = original_x + 55.55
    n1.mapped_x = new_x
    print(f"Modified Note 1 mapped_x to: {new_x}")
    
    # 3. Modify bbox (simulation of user interaction)
    m1_bbox_original = m1.bbox_x1
    m1_bbox_new = (m1_bbox_original or 0) + 123.45
    m1.bbox_x1 = m1_bbox_new
    print(f"Modified Measure 1 bbox_x1 to: {m1_bbox_new}")
    
    # 4. Save to a temporary file
    temp_out = r"c:\Users\DiCiA\PycharmProjects\NoteFlow Studio-Program\Save\test_output.musicxml"
    exporter.export_musicxml(score1, temp_out)
    print(f"Exported to {temp_out}")
    
    # 5. Load the temporary file
    print("2. Parsing exported file...")
    score2 = parser.parse(temp_out)
    m1_loaded = score2.measures[0]
    n1_loaded = m1_loaded.notes[0]
    
    # 6. Apply distribute_measures_across_pages (this is what caused the bug)
    print("3. Applying distribute_measures_across_pages (simulate main_window)...")
    parser.distribute_measures_across_pages(score2, page_count=2, dpi=200, pdf_renderer=None)
    
    # 7. Check if coordinates match
    print("--- RESULTS ---")
    print(f"Expected Note mapped_x: {new_x}")
    print(f"Loaded Note mapped_x:   {n1_loaded.mapped_x}")
    if abs(new_x - (n1_loaded.mapped_x or 0)) < 0.01:
        print("SUCCESS: Note coordinate matches perfectly!")
    else:
        print("FAILED: Note coordinate does not match!")
        
    print(f"Expected Measure bbox_x1: {m1_bbox_new}")
    print(f"Loaded Measure bbox_x1:   {m1_loaded.bbox_x1}")
    if abs(m1_bbox_new - (m1_loaded.bbox_x1 or 0)) < 0.01:
        print("SUCCESS: Measure coordinate matches perfectly!")
    else:
        print("FAILED: Measure coordinate does not match!")

if __name__ == "__main__":
    test_save_load()
