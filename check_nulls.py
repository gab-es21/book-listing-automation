import pathlib

for p in pathlib.Path("src").rglob("*.py"):
    data = p.read_bytes()
    if b"\x00" in data:
        print("⚠️ corrompido:", p)
