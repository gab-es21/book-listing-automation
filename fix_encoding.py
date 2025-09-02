import sys, pathlib

def is_utf16_bom(b: bytes) -> bool:
    return b.startswith(b"\xff\xfe") or b.startswith(b"\xfe\xff")

def fix_file(p: pathlib.Path):
    data = p.read_bytes()
    if b"\x00" in data or is_utf16_bom(data[:4]):
        try:
            text = data.decode("utf-16")
            p.write_text(text, encoding="utf-8", newline="\n")
            print(f"[fixed] {p}")
        except Exception as e:
            print(f"[skip] {p} -> {e}")

base = pathlib.Path(".")
targets = list(base.rglob("*.py"))
for f in targets:
    fix_file(f)

print("Done.")
