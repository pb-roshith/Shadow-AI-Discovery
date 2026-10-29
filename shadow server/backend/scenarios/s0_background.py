import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scenarios.activity import s0
if __name__ == "__main__":
    s0()
