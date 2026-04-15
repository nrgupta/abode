import os
import sys

from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sheets.google_sheets import clear_sheets

if __name__ == "__main__":
    print("Clearing Google Sheets...")
    clear_sheets()
    print("Done.")
