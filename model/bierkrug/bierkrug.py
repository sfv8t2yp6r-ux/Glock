"""Billet-Bierkrug 0,5 l aus Aluminium (gefräster Maßkrug-Stil).

Erzeugt bierkrug_0p5l.step, bierkrug_0p5l.stl und ein kompaktes Mesh (.bin)
für den Web-Viewer. Benötigt: pip install cadquery numpy
"""
import math
import struct
from pathlib import Path

import cadquery as cq
import numpy as np

OUT = Path(__file__).resolve().parent

# ---------------------------------------------------------------- Parameter
R_IN = 38.0            # Innenradius Bohrung (Ø76)
R_IN_FILLET = 6.0      # Radius Innenboden
T_BOTTOM = 10.0        # Bodenstärke
FREEBOARD = 20.0       # Abstand Eichstrich -> Oberkante
TARGET_ML = 500.0

R_END = 43.0           # Außenradius oben/unten (Ø86)
R_MID = 45.5           # Außenradius Bauchung (Ø91)

ROWS = 4
PER_ROW = 9
RING_R = 9.4           # Ringnut Mittenradius
RING_TUBE = 2.6        # Ringnut Rohrradius (Kugelfräser Ø5,2)
POCKET_R = 12.0        # Planfläche Außenradius
POCKET_DEPTH = 0.8     # Tiefe der Planfläche

HANDLE_D = 16.0


# ------------------------------------------------------- Innenvolumen lösen
def cavity(depth):
    prof = (cq.Workplane("XZ").moveTo(0, 0).lineTo(R_IN, 0)
            .lineTo(R_IN, depth).lineTo(0, depth).close())
    solid = prof.revolve(360, (0, 0, 0), (0, 1, 0))
    return solid.faces("<Z").edges().fillet(R_IN_FILLET)


def volume_ml(h):
    return cavity(h).val().Volume() / 1000.0


lo, hi = 80.0, 140.0
for _ in range(40):
    mid = (lo + hi) / 2
    if volume_ml(mid) < TARGET_ML:
        lo = mid
    else:
        hi = mid
H_FILL = round((lo + hi) / 2, 2)
DEPTH = H_FILL + FREEBOARD
H = T_BOTTOM + DEPTH
print(f"Füllhöhe 0,5 l: {H_FILL:.2f} mm über Innenboden")
print(f"Gesamthöhe: {H:.2f} mm, Randvoll: {volume_ml(DEPTH):.1f} ml")


# ---------------------------------------------------------------- Außenkontur
Z_BAND_LO = 12.0              # unterer glatter Fuß
Z_BAND_HI = H - 26.0          # oberer glatter Rand


def r_outer(z):
    """Bauchiges Profil: Radius als Funktion der Höhe (glatte Sinuskurve)."""
    t = min(max((z - 6.0) / (H - 12.0), 0.0), 1.0)
    return R_END + (R_MID - R_END) * math.sin(math.pi * t)


pts = [(r_outer(z), z) for z in np.linspace(6.0, H - 6.0, 25)]
body_prof = (cq.Workplane("XZ").moveTo(0, 0).lineTo(R_END - 1.0, 0)
             .lineTo(R_END, 1.0).lineTo(R_END, 6.0)
             .spline(pts[1:], includeCurrent=True)
             .lineTo(R_END, H - 1.0).lineTo(R_END - 1.0, H)
             .lineTo(0, H).close())
body = body_prof.revolve(360, (0, 0, 0), (0, 1, 0))

# Innenbohrung
body = body.cut(cavity(DEPTH + 5).translate((0, 0, T_BOTTOM)))
# Innenkante oben fasen
body = body.faces(">Z").edges("not %LINE").edges(
    cq.selectors.RadiusNthSelector(0)).chamfer(1.0)

# Zierrillen im oberen Rand + Eichstrich innen
for z in (H - 8.0, H - 12.0):
    groove = cq.Solid.makeTorus(R_END + 0.6, 1.0, cq.Vector(0, 0, z),
                                cq.Vector(0, 0, 1))
    body = body.cut(cq.Workplane().add(groove))
eich = cq.Solid.makeTorus(R_IN, 0.4, cq.Vector(0, 0, T_BOTTOM + H_FILL),
                          cq.Vector(0, 0, 1))
body = body.cut(cq.Workplane().add(eich))
# Fußrille
foot = cq.Solid.makeTorus(r_outer(9.0) + 0.6, 1.0, cq.Vector(0, 0, 9.0),
                          cq.Vector(0, 0, 1))
body = body.cut(cq.Workplane().add(foot))


# ---------------------------------------------------------- Ringmulden
def dimple_cutter(angle_deg, z):
    a = math.radians(angle_deg)
    d = cq.Vector(math.cos(a), math.sin(a), 0)
    rs = r_outer(z)
    plane_r = rs - POCKET_DEPTH
    # Planfläche: Zylinder von der Planebene nach außen
    pocket = cq.Solid.makeCylinder(POCKET_R, 6.0, d * plane_r + cq.Vector(0, 0, z), d)
    ring = cq.Solid.makeTorus(RING_R, RING_TUBE, d * plane_r + cq.Vector(0, 0, z), d)
    return pocket.fuse(ring)


span = Z_BAND_HI - Z_BAND_LO
pitch_z = span / ROWS
cutters = []
for row in range(ROWS):
    z = Z_BAND_LO + pitch_z * (row + 0.5)
    offset = (360 / PER_ROW) / 2 if row % 2 else 0.0
    for k in range(PER_ROW):
        ang = (offset + k * 360 / PER_ROW) % 360
        # Henkelseite (180°) freilassen
        if abs(((ang - 180) + 180) % 360 - 180) < 30:
            continue
        cutters.append(dimple_cutter(ang, z))
print(f"Mulden: {len(cutters)}")
body = body.cut(cq.Workplane().add(cq.Compound.makeCompound(cutters)))


# ---------------------------------------------------------------- Henkel
# D-förmiger Rundstab: waagerechte Stummel, zwei Bögen R16, senkrechter Griff.
z_top, z_bot = H - 18.0, 24.0
HB = 16.0                       # Biegeradius
x_in = -(R_IN + 1.5)            # Stummel beginnt in der Wand
x1 = -(R_END + 14.0)
x_out = x1 - HB
path = (cq.Workplane("XZ").moveTo(x_in, z_top).lineTo(x1, z_top)
        .radiusArc((x_out, z_top - HB), -HB)
        .lineTo(x_out, z_bot + HB)
        .radiusArc((x1, z_bot), -HB)
        .lineTo(x_in, z_bot))
profile = cq.Workplane(cq.Plane(origin=(x_in, 0, z_top), xDir=(0, 1, 0), normal=(-1, 0, 0))).circle(HANDLE_D / 2)
handle = profile.sweep(path, transition="round")
handle = handle.cut(cavity(DEPTH + 5).translate((0, 0, T_BOTTOM)))
krug = body.union(handle)
try:
    krug = krug.edges(cq.selectors.BoxSelector((-R_MID - 2, -12, 0), (-R_END + 3, 12, H))).fillet(2.0)
except Exception as e:  # Übergangsverrundung ist optional
    print("Henkel-Verrundung übersprungen:", e)

solid = krug.val()
print(f"Gültig: {solid.isValid()}, Materialvolumen: {solid.Volume()/1000:.1f} cm³, "
      f"Masse Al (2,70 g/cm³): {solid.Volume()/1000*2.70:.0f} g")
bb = solid.BoundingBox()
print(f"Bauraum: {bb.xlen:.1f} x {bb.ylen:.1f} x {bb.zlen:.1f} mm")

cq.exporters.export(krug, str(OUT / "bierkrug_0p5l.step"))
cq.exporters.export(krug, str(OUT / "bierkrug_0p5l.stl"), tolerance=0.1, angularTolerance=0.2)


# ------------------------------------------------- Mesh für den Web-Viewer
# Pro Fläche tesselliert: glatt innerhalb einer Fläche, scharfe Kanten dazwischen.
P, N, I = [], [], []
base = 0
for f in solid.Faces():
    vs, tris = f.tessellate(0.12, 0.25)
    if not tris:
        continue
    v = np.array([[p.x, p.y, p.z] for p in vs], dtype=np.float64)
    t = np.array(tris, dtype=np.int64)
    fn = np.cross(v[t[:, 1]] - v[t[:, 0]], v[t[:, 2]] - v[t[:, 0]])
    vn = np.zeros_like(v)
    for j in range(3):
        np.add.at(vn, t[:, j], fn)
    vn /= np.linalg.norm(vn, axis=1, keepdims=True) + 1e-12
    P.append(v); N.append(vn); I.append(t + base)
    base += len(v)
P = np.vstack(P).astype(np.float32)
N = np.vstack(N)
I = np.vstack(I).astype(np.uint32)
with open(OUT / "bierkrug_0p5l.bin", "wb") as fh:
    fh.write(struct.pack("<II", len(P), len(I)))
    fh.write(P.tobytes())
    fh.write(np.round(N * 127).astype(np.int8).tobytes())
    fh.write(I.tobytes())
print(f"Viewer-Mesh: {len(P)} Vertices, {len(I)} Dreiecke")
