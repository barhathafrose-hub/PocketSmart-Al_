"""Check Gemini connectivity. Run: python test_gemini.py [optional_image.jpg]"""
import sys
from PIL import Image
from gemini_utils import client, MODELS

for m in MODELS:
    try:
        r = client().models.generate_content(model=m, contents="Reply with one word: ready")
        print(f"OK   {m}: {r.text.strip()}")
        if len(sys.argv) > 1:
            img = Image.open(sys.argv[1])
            r = client().models.generate_content(model=m, contents=["Name the main colours in one line.", img])
            print("Image test:", r.text.strip())
        break
    except Exception as e:
        print(f"FAIL {m}: {type(e).__name__}: {e}")
