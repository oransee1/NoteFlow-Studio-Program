import xml.etree.ElementTree as ET
import glob

found = False
for f in glob.glob('**/*.musicxml', recursive=True) + glob.glob('**/*.xml', recursive=True):
    try:
        tree = ET.parse(f)
        root = tree.getroot()
        for part in root.findall('part'):
            for m in part.findall('measure'):
                for k, v in m.attrib.items():
                    if 'inf' in v.lower():
                        print(f"Found inf in {f} - Measure {m.get('number')}: {k}={v}")
                        found = True
                for n in m.findall('note'):
                    for k, v in n.attrib.items():
                        if 'inf' in v.lower():
                            print(f"Found inf in {f} - Note: {k}={v}")
                            found = True
    except Exception as e:
        pass
if not found: print('No inf found anywhere.')
