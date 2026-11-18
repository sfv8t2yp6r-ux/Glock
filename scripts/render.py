"""Render frames of model/glock18.blend.
usage: python3 scripts/render.py <outdir> <start> <end> [step] [res_percent] [samples]"""
import bpy, sys, os
a = sys.argv[1:]
out, s, e = a[0], int(a[1]), int(a[2])
step = int(a[3]) if len(a) > 3 else 1
pct = int(a[4]) if len(a) > 4 else 100
spp = int(a[5]) if len(a) > 5 else None
bpy.ops.wm.open_mainfile(filepath=os.path.join(os.path.dirname(__file__), "..", "model", "glock18.blend"))
sc = bpy.context.scene
sc.render.resolution_percentage = pct
if spp: sc.cycles.samples = spp
sc.cycles.device = 'CPU'
os.makedirs(out, exist_ok=True)
for f in range(s, e + 1, step):
    sc.frame_set(f)
    sc.render.filepath = os.path.join(out, f"f{f:04d}.png")
    bpy.ops.render.render(write_still=True)
