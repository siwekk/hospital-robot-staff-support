import json
from pathlib import Path
root = Path(__file__).resolve().parents[1]
s = json.loads((root / "phi_pilot_summary.json").read_text())
pts = sorted((float(k[3:]), v["coverage"]) for k, v in s.items())
usable = [p for p, cov in pts if 0.010 <= cov <= 0.10]
if len(usable) >= 3:
    grid = [usable[0], usable[len(usable) // 2], usable[-1]]
elif usable:
    grid = usable
else:
    grid = [p for p, _ in pts][:3]
(root / "phi_grid.json").write_text(json.dumps(grid))
print("pilot coverage by phi:", pts, "grid:", grid)
