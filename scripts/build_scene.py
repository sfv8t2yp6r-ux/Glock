"""
Glock 18 – procedural clay model + function animation (Blender / bpy).

Builds the model from extruded side profiles + lathed parts, sets up a
cut-away (section) view and keyframes the full firing cycle:
trigger pull -> trigger bar -> striker release -> ignition -> bullet travel ->
muzzle exit -> slide recoil / ejection -> feeding the next round.

Modelling units: 1 unit = 1 cm (everything lives under the root empty
"Glock18", which is scaled 0.01 so the scene is in real-world metres).
Axes: +X = muzzle direction, +Z = up, +Y = left side of the pistol.

Usage:  python3 scripts/build_scene.py  [out.blend]
"""
import bpy, bmesh, math, sys, os
from mathutils import Vector, Matrix

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "..", "model", "glock18.blend")
OUT = os.path.abspath(OUT)

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
col = scene.collection
FPS, F_END = 30, 450
scene.render.fps = FPS
scene.frame_start, scene.frame_end = 1, F_END

# ----------------------------------------------------------------- helpers
def clamp(x, a=0.0, b=1.0): return max(a, min(b, x))
def smooth(t): t = clamp(t); return t * t * (3 - 2 * t)
def ramp(f, a, b): return smooth((f - a) / (b - a))
def lin(f, a, b): return clamp((f - a) / (b - a))
def lerp(a, b, t): return a + (b - a) * t

def link(obj, parent=None):
    col.objects.link(obj)
    if parent is not None:
        obj.parent = parent
        obj.matrix_parent_inverse = parent.matrix_basis.inverted() if parent.parent else Matrix()
    return obj

def new_obj(name, bm):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me); bm.free()
    ob = bpy.data.objects.new(name, me)
    col.objects.link(ob)
    return ob

def extrude(name, pts, width, y0=0.0):
    """Extrude a closed (x,z) profile along Y, centred at y0."""
    bm = bmesh.new()
    a = [bm.verts.new((x, y0 - width / 2, z)) for x, z in pts]
    b = [bm.verts.new((x, y0 + width / 2, z)) for x, z in pts]
    bm.faces.new(a); bm.faces.new(list(reversed(b)))
    n = len(pts)
    for i in range(n):
        j = (i + 1) % n
        bm.faces.new([a[i], a[j], b[j], b[i]])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return new_obj(name, bm)

def box(name, x0, x1, y0, y1, z0, z1):
    return extrude(name, [(x0, z0), (x1, z0), (x1, z1), (x0, z1)], y1 - y0, (y0 + y1) / 2)

def lathe(name, prof, seg=48, closed=False):
    """Revolve (x, r) profile around the X axis."""
    bm = bmesh.new()
    rings = []
    for x, r in prof:
        if r < 1e-6:
            rings.append([bm.verts.new((x, 0, 0))])
        else:
            rings.append([bm.verts.new((x, r * math.cos(2 * math.pi * i / seg), r * math.sin(2 * math.pi * i / seg))) for i in range(seg)])
    pairs = list(zip(rings, rings[1:])) + ([(rings[-1], rings[0])] if closed else [])
    for A, B in pairs:
        if len(A) == 1 and len(B) == 1: continue
        for i in range(seg):
            j = (i + 1) % seg
            if len(A) == 1: bm.faces.new([A[0], B[j], B[i]])
            elif len(B) == 1: bm.faces.new([A[i], A[j], B[0]])
            else: bm.faces.new([A[i], A[j], B[j], B[i]])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return new_obj(name, bm)

def cyl_y(name, x, z, r, y0, y1, seg=32):
    o = lathe(name, [(y0, 0), (y0, r), (y1, r), (y1, 0)], seg)
    # lathe builds along X -> rotate so the axis is Y, then move
    o.data.transform(Matrix.Rotation(math.radians(90), 4, 'Z'))
    o.data.transform(Matrix.Translation((x, 0, z)))
    return o

def cyl_z(name, x, y, r, z0, z1, seg=24):
    o = lathe(name, [(z0, 0), (z0, r), (z1, r), (z1, 0)], seg)
    o.data.transform(Matrix.Rotation(math.radians(-90), 4, 'Y'))
    o.data.transform(Matrix.Translation((x, y, 0)))
    return o

def bake(obj):
    dg = bpy.context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(obj.evaluated_get(dg), preserve_all_data_layers=True, depsgraph=dg)
    old = obj.data
    obj.modifiers.clear()
    obj.data = me
    if old.users == 0: bpy.data.meshes.remove(old)

def bevel(obj, w, segs=3, angle=35):
    m = obj.modifiers.new("bev", 'BEVEL')
    m.width = w; m.segments = segs; m.limit_method = 'ANGLE'
    m.angle_limit = math.radians(angle); m.use_clamp_overlap = True
    bake(obj)

def boolean(obj, cutter, op='DIFFERENCE', keep=False):
    cutters = cutter if isinstance(cutter, (list, tuple)) else [cutter]
    for c in cutters:
        m = obj.modifiers.new("bool", 'BOOLEAN')
        m.object = c; m.operation = op; m.solver = 'MANIFOLD'
        m.material_mode = 'TRANSFER'
        if not c.data.materials and obj.data.materials: c.data.materials.append(obj.data.materials[0])
        bake(obj)
        if not keep: bpy.data.objects.remove(c, do_unlink=True)

def join(objs, name):
    base = objs[0]
    bm = bmesh.new()
    for o in objs:
        tmp = o.data.copy(); tmp.transform(o.matrix_world)
        bm.from_mesh(tmp); bpy.data.meshes.remove(tmp)
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    # materials: concatenate in order (each source assumed single material)
    ob = bpy.data.objects.new(name, me); col.objects.link(ob)
    for o in objs:
        for s in o.material_slots: ob.data.materials.append(s.material)
    # material indices: offsets per source
    off, fi = 0, 0
    for o in objs:
        n = len(o.data.polygons)
        for p in ob.data.polygons[fi:fi + n]:
            p.material_index = off + p.material_index
        fi += n; off += max(1, len(o.material_slots))
    for o in objs: bpy.data.objects.remove(o, do_unlink=True)
    return ob

def finish(obj, angle=38):
    me = obj.data
    me.shade_smooth()
    try: me.set_sharp_from_angle(angle=math.radians(angle))
    except Exception: pass

def setmat(obj, m):
    obj.data.materials.clear(); obj.data.materials.append(m)
    return obj

# ---------------------------------------------------------------- materials
OPACITY_NODES = []
def material(name, color, rough=0.6, metal=0.0, bump=0.0, emit=None, emit_strength=0.0, ghost=False):
    m = bpy.data.materials.new(name); m.use_nodes = True
    nt = m.node_tree; N = nt.nodes; L = nt.links
    bsdf = N.get('Principled BSDF'); out = N.get('Material Output')
    bsdf.inputs['Base Color'].default_value = (*color, 1)
    bsdf.inputs['Roughness'].default_value = rough
    bsdf.inputs['Metallic'].default_value = metal
    if bump:
        tex = N.new('ShaderNodeTexNoise'); tex.inputs['Scale'].default_value = 3.2
        tco = N.new('ShaderNodeTexCoord'); L.new(tco.outputs['Object'], tex.inputs['Vector'])
        tex.inputs['Detail'].default_value = 6.0
        b = N.new('ShaderNodeBump'); b.inputs['Strength'].default_value = bump
        b.inputs['Distance'].default_value = 0.012
        L.new(tex.outputs['Fac'], b.inputs['Height']); L.new(b.outputs['Normal'], bsdf.inputs['Normal'])
    if emit:
        bsdf.inputs['Emission Color'].default_value = (*emit, 1)
        bsdf.inputs['Emission Strength'].default_value = emit_strength
    if ghost:
        val = N.new('ShaderNodeValue'); val.name = 'Opacity'; val.outputs[0].default_value = 1.0
        tr = N.new('ShaderNodeBsdfTransparent'); mix = N.new('ShaderNodeMixShader')
        L.new(val.outputs[0], mix.inputs[0]); L.new(tr.outputs[0], mix.inputs[1])
        L.new(bsdf.outputs[0], mix.inputs[2]); L.new(mix.outputs[0], out.inputs['Surface'])
        OPACITY_NODES.append(val)
    return m

CLAY = (0.50, 0.50, 0.51)
M = {
    'clay':    material('Clay', CLAY, 0.62),
    'grip':    material('ClayGrip', CLAY, 0.75, bump=0.18),
    'barrel':  material('ClayBarrel', (0.40, 0.40, 0.41), 0.5),
    'section': material('SectionCut', (0.55, 0.20, 0.12), 0.7),
    'moving':  material('MovingParts', (0.26, 0.36, 0.50), 0.45, 0.2),
    'spring':  material('Spring', (0.12, 0.12, 0.13), 0.35, 0.8),
    'brass':   material('Brass', (0.72, 0.50, 0.22), 0.32, 0.85),
    'copper':  material('Copper', (0.70, 0.35, 0.18), 0.35, 0.85),
    'primer':  material('Primer', (0.75, 0.75, 0.75), 0.3, 0.9),
    'mag':     material('MagBody', (0.30, 0.30, 0.31), 0.6),
    'flash':   material('MuzzleFlash', (1, 0.6, 0.2), 1.0, emit=(1.0, 0.42, 0.08), emit_strength=7),
    'gas':     material('PropellantGas', (1, 0.5, 0.2), 1.0, emit=(1.0, 0.38, 0.08), emit_strength=3.5),
}
GHOST = {}
def ghost_of(m):
    if m.name not in GHOST:
        g = m.copy(); g.name = m.name + "_ghost"
        nt = g.node_tree; N = nt.nodes; L = nt.links
        val = N.new('ShaderNodeValue'); val.name = 'Opacity'; val.outputs[0].default_value = 1.0
        tr = N.new('ShaderNodeBsdfTransparent'); mix = N.new('ShaderNodeMixShader')
        L.new(val.outputs[0], mix.inputs[0]); L.new(tr.outputs[0], mix.inputs[1])
        L.new(N.get('Principled BSDF').outputs[0], mix.inputs[2]); L.new(mix.outputs[0], N.get('Material Output').inputs['Surface'])
        OPACITY_NODES.append(val)
        GHOST[m.name] = g
    return GHOST[m.name]

# ------------------------------------------------------------------ rigs
root = bpy.data.objects.new("Glock18", None); col.objects.link(root)
root.scale = (0.01, 0.01, 0.01)
def empty(name, loc=(0, 0, 0), parent=root):
    e = bpy.data.objects.new(name, None); e.location = loc
    e.empty_display_size = 1.0
    col.objects.link(e); e.parent = parent
    return e
def attach(obj, parent):
    obj.parent = parent
    obj.matrix_parent_inverse = parent.matrix_basis.inverted() if parent is not root else Matrix()
    return obj

slide_rig = empty("SlideRig")
frame_rig = empty("FrameRig")
BORE = 1.45          # bore axis height
XB = 4.4             # breech face / chamber rear
XM = 18.45           # barrel muzzle

# ================================================================== SLIDE
slide = extrude("Slide", [(0.05, 0.0), (18.0, 0.0), (18.6, 0.55), (18.6, 2.72), (18.42, 2.9),
                          (0.22, 2.9), (0.0, 2.68)], 2.55)
bevel(slide, 0.16, 3)
setmat(slide, M['clay'])
# sights (union)
rs = extrude("RearSight", [(0.45, 2.85), (1.35, 2.85), (1.35, 3.30), (1.05, 3.42), (0.45, 3.42)], 1.15)
bevel(rs, 0.06, 2)
notch = box("notch", 0.3, 1.6, -0.17, 0.17, 3.18, 3.6)
boolean(rs, notch)
fs = extrude("FrontSight", [(17.35, 2.85), (17.95, 2.85), (17.95, 3.38), (17.65, 3.38)], 0.32)
bevel(fs, 0.05, 2)
for o in (rs, fs): setmat(o, M['clay'])
boolean(slide, [rs, fs], 'UNION')
# rear serrations (both sides)
cut = []
for i in range(11):
    x = 0.75 + i * 0.30
    for side in (1, -1):
        y0 = side * 1.275
        cut.append(extrude(f"serr{i}{side}", [(x, 0.25), (x + 0.13, 0.25), (x + 0.13 + 0.05, 2.45), (x + 0.05, 2.45)],
                           0.16, y0))
serr = join(cut, "Serrations")
boolean(slide, serr)
# ejection port (right side = -Y), compensator slot (G18C), muzzle + rod holes
boolean(slide, box("port", XB, 8.7, -2.0, 0.35, 1.40, 4.0))
boolean(slide, box("comp", 15.2, 17.0, -0.42, 0.42, 2.4, 4.0))
mh = lathe("muzzlehole", [(17.5, 0), (17.5, 0.72), (19.5, 0.72), (19.5, 0)]); mh.data.transform(Matrix.Translation((0, 0, BORE)))
boolean(slide, mh)
rodhole = lathe("rodhole", [(17.5, 0), (17.5, 0.32), (19.5, 0.32), (19.5, 0)]); rodhole.data.transform(Matrix.Translation((0, 0, 0.38)))
boolean(slide, rodhole)
# interior (barrel channel, breech/rammer area, striker channel)
boolean(slide, box("inner", XB, 18.0, -0.97, 0.97, -1.0, 2.68))
boolean(slide, box("rammer", 0.9, XB + 0.01, -1.0, 1.0, -1.0, 0.78))
boolean(slide, box("legslot", 0.5, XB + 0.01, -0.32, 0.32, -1.0, 1.6))
sc = lathe("strikerchan", [(0.2, 0), (0.2, 0.26), (XB + 0.05, 0.26), (XB + 0.05, 0)]); sc.data.transform(Matrix.Translation((0, 0, BORE)))
boolean(slide, sc)
finish(slide)

# selector switch (left side, +Y) and extractor (right side, -Y)
sel_hub = cyl_y("SelectorHub", 1.55, 2.05, 0.36, 1.2, 1.46)
sel_lever = extrude("SelectorLever", [(1.4, 2.05), (1.7, 2.05), (1.05, 1.15), (0.78, 1.25)], 0.12, 1.42)
selector = join([sel_hub, sel_lever], "Selector"); bevel(selector, 0.03, 2); finish(selector)
setmat(selector, M['clay'])
extractor = extrude("Extractor", [(3.6, 1.62), (5.9, 1.62), (5.9, 2.02), (3.6, 2.02)], 0.08, -1.30)
bevel(extractor, 0.02, 2); setmat(extractor, M['clay']); finish(extractor)

# ================================================================== FRAME
receiver = extrude("Receiver", [(0.55, 0.0), (17.0, 0.0), (17.12, -0.2), (17.12, -1.15), (16.85, -1.5),
                                (2.4, -1.5), (1.4, -1.25), (0.65, -1.0), (0.12, -0.78), (-0.12, -0.48), (-0.02, -0.15)], 2.5)
bevel(receiver, 0.14, 3)

def backstrap_x(z): return 1.95 + 0.42 * (z + 1.6) - 0.17 * math.sin(math.pi * clamp((z + 1.6) / -8.8))
def frontstrap_x(z): return 6.6 + 0.42 * (z + 4.4)
grip_pts = [(backstrap_x(-0.9) + 0.25, -0.9), (frontstrap_x(-0.9), -0.9)]
zs = [-0.9 - i * (4.6 - 0.9) / 6 for i in range(1, 7)]
grip_pts += [(frontstrap_x(z), z) for z in zs]
NZ = 36
for i in range(NZ + 1):
    t = i / NZ; z = -4.6 + t * (-10.25 + 4.6)
    off = -0.34 * abs(math.sin(3 * math.pi * t)) ** 0.8
    grip_pts.append((frontstrap_x(z) + off * 0.92, z - off * 0.39 * -1))
grip_pts += [(frontstrap_x(-10.6) + 0.12, -10.6), (backstrap_x(-10.6) + 0.15, -10.6)]
for i in range(1, 16):
    z = -10.6 + i * (10.6 - 1.25) / 15
    grip_pts.append((backstrap_x(z), z))
grip = extrude("Grip", grip_pts, 3.0)
bevel(grip, 0.55, 4, 30)
setmat(grip, M['grip'])

guard = extrude("Guard", [(6.9, -1.4), (12.6, -1.4), (12.45, -2.2), (12.35, -3.9), (12.58, -4.05), (12.58, -4.32),
                          (12.3, -4.45), (12.0, -4.72), (11.5, -4.86), (8.6, -4.86), (7.6, -4.76), (6.9, -4.5), (6.5, -4.0)], 1.45)
bevel(guard, 0.3, 3)
hole = extrude("GuardHole", [(7.4, -1.3), (11.8, -1.3), (11.95, -1.9), (11.86, -3.9), (11.62, -4.28), (11.3, -4.38),
                             (8.7, -4.38), (7.9, -4.28), (7.35, -3.85), (7.12, -3.1), (7.2, -2.1)], 4.0)
for o in (receiver, guard): setmat(o, M['clay'])
boolean(receiver, [grip, guard], 'UNION')
frame = receiver; frame.name = "Frame"
boolean(frame, hole)
# accessory rail: side grooves + cross slot
boolean(frame, box("railL", 12.9, 17.4, 1.02, 2.0, -1.33, -1.12))
boolean(frame, box("railR", 12.9, 17.4, -2.0, -1.02, -1.33, -1.12))
boolean(frame, box("railX", 14.5, 15.05, -2, 2, -2.0, -1.28))
# trigger / magazine cavities
boolean(frame, box("cavity", 0.75, 12.4, -1.12, 1.12, -1.32, 0.06))
boolean(frame, box("trigslot", 8.75, 10.6, -0.4, 0.4, -1.7, -1.0))
A = Vector((-0.371, 0, -0.928)); NRM = Vector((0.928, 0, -0.371))   # magazine axis / forward normal
TOPC = Vector((5.3, 0, 0.2))                                          # top round centre
def oriented_box(name, u0, u1, n0, n1, y0, y1):
    pts = [TOPC + A * u + NRM * n for u, n in ((u0, n0), (u0, n1), (u1, n1), (u1, n0))]
    return extrude(name, [(p.x, p.z) for p in pts], y1 - y0, (y0 + y1) / 2)
boolean(frame, oriented_box("magwell", -2.0, 12.5, -1.78, 1.78, -1.05, 1.05))
finish(frame, 40)

# small frame parts (pins / levers / mag release) – split by side later
frame_bits = [
    cyl_y("TrigPin", 9.45, -1.25, 0.16, -1.30, 1.30),
    cyl_y("LockPin", 6.9, -0.75, 0.16, -1.30, 1.30),
    cyl_y("RearPin", 1.3, -0.55, 0.14, -1.30, 1.30),
]
slide_stop = extrude("SlideStop", [(6.2, -0.05), (7.6, -0.05), (7.6, -0.45), (6.9, -0.6), (6.2, -0.45)], 0.12, 1.30)
takedown = extrude("Takedown", [(10.3, -0.05), (11.1, -0.05), (11.1, -0.42), (10.3, -0.42)], 2.68)
magrel = extrude("MagRelease", [(6.7, -2.0), (7.35, -2.0), (7.35, -2.75), (6.7, -2.75)], 3.2)
for o in frame_bits + [slide_stop, takedown, magrel]:
    bevel(o, 0.04, 2); setmat(o, M['clay']); finish(o)

# ================================================================== BARREL
bar_tube = lathe("BarrelTube", [(8.35, 0.47), (8.35, 0.66), (XM - 0.05, 0.66), (XM, 0.6), (XM, 0.47)], 48, closed=True)
bar_tube.data.transform(Matrix.Translation((0, 0, BORE)))
hood = box("Hood", XB, 8.4, -0.8, 0.8, 0.85, 2.72)
bevel(hood, 0.08, 2)
chamber = lathe("chamber", [(XB - 0.1, 0), (XB - 0.1, 0.505), (6.35, 0.505), (6.5, 0.47), (8.5, 0.47), (8.5, 0)]); chamber.data.transform(Matrix.Translation((0, 0, BORE)))
boolean(hood, chamber)
lug = box("Lug", 7.0, 8.2, -0.55, 0.55, 0.45, 0.9); bevel(lug, 0.06, 2)
for o in (bar_tube, hood, lug): setmat(o, M['barrel'])
boolean(hood, [bar_tube, lug], 'UNION')
barrel = hood; barrel.name = "Barrel"
for i in range(4):
    boolean(barrel, cyl_z(f"cp{i}", 15.45 + i * 0.42, 0, 0.12, BORE, BORE + 1.0))
finish(barrel)

# ================================================================== SECTION SPLIT
def section(obj, parent):
    """Split a body at y=0: far half (+Y, stays) and near half (-Y, fades)."""
    far = obj.copy(); far.data = obj.data.copy(); col.objects.link(far); far.name = obj.name + "_far"
    near = obj; near.name = obj.name + "_near"
    cf = box("cutF", -20, 40, 0.0, 10, -20, 20); setmat(cf, M['section'])
    cn = box("cutN", -20, 40, -10, 0.0, -20, 20); setmat(cn, M['section'])
    boolean(far, cf, 'INTERSECT'); boolean(near, cn, 'INTERSECT')
    for o in (far, near): finish(o)
    for i, s in enumerate(near.material_slots):
        near.material_slots[i].material = ghost_of(s.material)
    attach(far, parent); attach(near, parent)
    return far, near

NEAR = []  # objects that fade + slide out toward the camera
slide_far, slide_near = section(slide, slide_rig); NEAR.append(slide_near)
frame_far, frame_near = section(frame, frame_rig); NEAR.append(frame_near)
attach(selector, slide_rig)
setmat(extractor, ghost_of(M['clay'])); attach(extractor, slide_rig); NEAR.append(extractor)
for o in frame_bits + [takedown, magrel]:
    f, n = section(o, frame_rig); NEAR.append(n)
attach(slide_stop, frame_rig)

barrel_pivot = empty("BarrelPivot", (17.6, 0, BORE))
barrel_far, barrel_near = section(barrel, root)
for o in (barrel_far, barrel_near): attach(o, barrel_pivot)
NEAR.append(barrel_near)

# ================================================================== MAGAZINE
mag = oriented_box("Magazine", -0.42, 11.0, -1.62, 1.62, -0.92, 0.92); bevel(mag, 0.08, 2)
boolean(mag, oriented_box("maginner", -1.0, 10.85, -1.5, 1.5, -0.80, 0.80))
setmat(mag, M['mag'])
base = extrude("BasePlate", [(frontstrap_x(-10.6) + 0.35, -10.55), (frontstrap_x(-10.6) + 0.25, -11.15), (backstrap_x(-10.6) - 0.05, -11.15),
                             (backstrap_x(-10.6) - 0.1, -10.55)], 2.95)
bevel(base, 0.18, 3); setmat(base, M['clay'])
mag_far, mag_near = section(mag, frame_rig); NEAR.append(mag_near)
base_far, base_near = section(base, frame_rig); NEAR.append(base_near)

# ================================================================== CARTRIDGES
CASE_L, BUL_L, BUL_SEAT = 1.915, 1.55, 1.42
case_prof = [(0, 0), (0, 0.495), (0.12, 0.495), (0.14, 0.40), (0.24, 0.40), (0.30, 0.493), (CASE_L, 0.482), (CASE_L, 0.45), (CASE_L - 0.05, 0.45), (CASE_L - 0.05, 0)]
bul_prof = [(0, 0), (0, 0.452), (0.72, 0.452)] + [(0.72 + (BUL_L - 0.72) * math.sin(t * math.pi / 2), 0.452 * math.cos(t * math.pi / 2) ** 0.85) for t in [i / 10 for i in range(1, 10)]] + [(BUL_L, 0)]

def make_case(name):
    c = lathe(name + "_case", case_prof, 40); setmat(c, M['brass'])
    p = lathe(name + "_primer", [(-0.01, 0), (-0.01, 0.22), (0.02, 0.22), (0.02, 0)], 24); setmat(p, M['primer'])
    o = join([c, p], name); finish(o, 50); return o
def make_bullet(name):
    b = lathe(name, bul_prof, 40); setmat(b, M['copper']); finish(b, 50); return b
def make_round(name):
    c = make_case(name + "c"); b = make_bullet(name + "b")
    b.data.transform(Matrix.Translation((2.97 - BUL_L, 0, 0)))  # bullet base seated inside the case
    o = join([c, b], name); finish(o, 50); return o

chamber_case = make_case("FiredCase"); attach(chamber_case, root)
bullet = make_bullet("Bullet"); attach(bullet, root)
BUL_BASE0 = XB + 2.97 - BUL_L

N_MAG = 15
def mag_pos(i):
    """Rim-centre position of round i (0 = top) in the magazine."""
    c = Vector((3.8, 0, 0.2)) + A * (0.56 * i)
    y = 0.27 if i % 2 == 0 else -0.27
    if i == 0: y = 0.2
    return Vector((c.x, y, c.z))
rounds = []
for i in range(N_MAG):
    r = make_round(f"Round{i:02d}"); attach(r, frame_rig); rounds.append(r)

# ================================================================== FIRE CONTROL
trig_pivot = empty("TriggerPivot", (9.45, 0, -1.25), frame_rig)
trig = extrude("Trigger", [(9.12, -0.95), (9.78, -0.95), (9.86, -1.6), (9.80, -2.4), (9.95, -3.1), (10.12, -3.62),
                           (9.86, -3.78), (9.55, -3.42), (9.30, -2.6), (9.18, -1.8)], 0.56)
bevel(trig, 0.09, 3)
tsafe = extrude("TriggerSafety", [(9.86, -1.9), (10.0, -2.0), (10.05, -3.0), (10.2, -3.45), (10.02, -3.5), (9.9, -3.0)], 0.16)
bevel(tsafe, 0.03, 2)
for o in (trig, tsafe): setmat(o, M['moving']); finish(o)
trig = join([trig, tsafe], "Trigger"); finish(trig)
attach(trig, trig_pivot)

bar_pivot = empty("TriggerBarPivot", (9.4, -1.06, -1.7), frame_rig)
tb_pts = [(9.7, -1.6), (9.7, -1.85), (6.0, -1.0), (2.95, -0.75), (2.95, -0.5), (6.0, -0.75)]
tbar = extrude("TriggerBar", tb_pts, 0.12, -1.06)
cruc = box("Cruciform", 2.70, 2.95, -1.12, 0.15, -0.78, 0.35)
bevel(tbar, 0.03, 2); bevel(cruc, 0.03, 2)
for o in (tbar, cruc): setmat(o, M['moving'])
tbar = join([tbar, cruc], "TriggerBar"); finish(tbar)
attach(tbar, bar_pivot)

# striker (local: tip at x=0, pointing +X), lives in the slide
strk = lathe("StrikerBody", [(0, 0), (0, 0.06), (-0.35, 0.07), (-0.42, 0.14), (-1.55, 0.14), (-1.55, 0.21), (-1.67, 0.21),
                             (-1.67, 0.09), (-3.2, 0.09), (-3.2, 0)], 32)
leg = box("StrikerLeg", -1.95, -1.70, -0.12, 0.12, -1.35, 0.0); bevel(leg, 0.03, 2)
for o in (strk, leg): setmat(o, M['moving'])
striker = join([strk, leg], "Striker"); finish(striker)
STRIKER_REST = 4.0
striker.location = (STRIKER_REST, 0, BORE)
attach(striker, slide_rig)

def helix(name, L, r, turns, wire, mat):
    cu = bpy.data.curves.new(name, 'CURVE'); cu.dimensions = '3D'
    sp = cu.splines.new('POLY'); n = int(turns * 24)
    sp.points.add(n)
    for i in range(n + 1):
        t = i / n; a = 2 * math.pi * turns * t
        sp.points[i].co = (L * t, r * math.cos(a), r * math.sin(a), 1)
    cu.bevel_depth = wire; cu.bevel_resolution = 3
    o = bpy.data.objects.new(name, cu); col.objects.link(o)
    o.data.materials.append(mat)
    return o

SPR_FIX = 0.45
striker_spring = helix("StrikerSpring", 1.0, 0.17, 9, 0.035, M['spring'])
striker_spring.location = (SPR_FIX, 0, BORE); attach(striker_spring, slide_rig)
ROD_Z, ROD_X0, ROD_X1 = 0.38, 8.3, 17.7
recoil_spring = helix("RecoilSpring", 1.0, 0.27, 16, 0.045, M['spring'])
recoil_spring.location = (ROD_X0, 0, ROD_Z); attach(recoil_spring, frame_rig)
rod = lathe("GuideRod", [(ROD_X0 - 0.3, 0), (ROD_X0 - 0.3, 0.3), (ROD_X0, 0.3), (ROD_X0, 0.12), (ROD_X1 + 0.1, 0.12), (ROD_X1 + 0.1, 0)], 24)
rod.data.transform(Matrix.Translation((0, 0, ROD_Z))); setmat(rod, M['clay']); finish(rod); attach(rod, frame_rig)

# ================================================================== EFFECTS
def flash_mesh(name, petals, length, width, seed=1):
    import random; rnd = random.Random(seed)
    parts = []
    core = lathe(name + "core", [(0, 0)] + [(length * 0.35 * t, width * 1.4 * math.sin(math.pi * t) ** 0.6) for t in [i / 12 for i in range(1, 12)]] + [(length * 0.35, 0)], 20)
    parts.append(core)
    for k in range(petals):
        p = lathe(f"{name}p{k}", [(0, 0)] + [(length * t, width * math.sin(math.pi * t ** 0.7) ** 0.8 * (1 - t) ** 0.3) for t in [i / 14 for i in range(1, 14)]] + [(length, 0)], 12)
        ang = 2 * math.pi * k / petals + rnd.uniform(-0.2, 0.2)
        tilt = math.radians(rnd.uniform(25, 60)) if k % 2 else math.radians(rnd.uniform(5, 18))
        sc = rnd.uniform(0.55, 1.0) * (0.55 if k % 2 else 1.0)
        mtx = Matrix.Rotation(ang, 4, 'X') @ Matrix.Rotation(tilt, 4, 'Z') @ Matrix.Scale(sc, 4)
        p.data.transform(mtx); parts.append(p)
    for o in parts: setmat(o, M['flash'])
    o = join(parts, name); finish(o, 80)
    o.visible_shadow = False
    return o

flash = flash_mesh("MuzzleFlash", 8, 7.0, 0.9); flash.location = (XM + 0.1, 0, BORE); attach(flash, root)
comp_flash = flash_mesh("CompFlash", 4, 2.6, 0.35, 7); comp_flash.rotation_euler = (0, math.radians(-75), 0)
comp_flash.location = (16.1, 0, 2.8); attach(comp_flash, root)
gas = lathe("Gas", [(0, 0), (0, 0.43), (1, 0.43), (1, 0)], 32); setmat(gas, M['gas']); gas.visible_shadow = False
gas.location = (XB + CASE_L - 0.05, 0, BORE); attach(gas, root)

def point_light(name, loc, color):
    ld = bpy.data.lights.new(name, 'POINT'); ld.color = color; ld.shadow_soft_size = 0.01
    o = bpy.data.objects.new(name, ld); o.location = loc; col.objects.link(o); attach(o, root)
    return o
flash_light = point_light("FlashLight", (XM + 2.5, -2.0, BORE), (1.0, 0.55, 0.2))
prime_light = point_light("PrimerLight", (XB + 0.5, -1.0, BORE), (1.0, 0.6, 0.25))

# ================================================================== CAMERA + LIGHTS
cam_d = bpy.data.cameras.new("Cam"); cam_d.lens = 70; cam_d.sensor_width = 36; cam_d.sensor_fit = 'AUTO'
cam_d.clip_start = 0.01
cam = bpy.data.objects.new("Camera", cam_d); col.objects.link(cam); scene.camera = cam
target = bpy.data.objects.new("CamTarget", None); col.objects.link(target)
tc = cam.constraints.new('TRACK_TO'); tc.target = target; tc.track_axis = 'TRACK_NEGATIVE_Z'; tc.up_axis = 'UP_Y'

def area(name, loc, size, energy, color=(1, 1, 1)):
    ld = bpy.data.lights.new(name, 'AREA'); ld.size = size; ld.energy = energy; ld.color = color
    o = bpy.data.objects.new(name, ld); col.objects.link(o)
    o.parent = cam; o.location = loc
    c = o.constraints.new('TRACK_TO'); c.target = target; c.track_axis = 'TRACK_NEGATIVE_Z'; c.up_axis = 'UP_Y'
    return o
area("Key", (0.45, 0.55, 0.15), 0.6, 9)
area("Fill", (-0.6, -0.1, 0.0), 0.8, 3, (0.92, 0.95, 1.0))
area("Rim", (0.0, 0.5, -0.9), 0.5, 8)
world = bpy.data.worlds.new("World"); scene.world = world; world.use_nodes = True
world.node_tree.nodes['Background'].inputs['Color'].default_value = (0.20, 0.205, 0.215, 1)
world.node_tree.nodes['Background'].inputs['Strength'].default_value = 0.3

# ================================================================== ANIMATION
# timeline (frames @30fps)
T_FADE = (70, 105)        # near halves fade out
T_PULL = (105, 168)       # trigger travel
T_DROP = (165, 172)       # connector drops trigger bar -> striker released
T_FIRE = (172, 176)       # striker hits primer
T_BUL = (177, 246)        # bullet in barrel (slow motion)
T_BACK = (246, 268)       # slide recoils
T_HOLD = 274
T_RET = (274, 294)        # slide returns, feeds next round
T_TREL = (262, 286)       # trigger released / reset
T_FADEIN = (318, 352)
SLIDE_TRAVEL = 3.4
BUL_EXIT = XM - BUL_L     # bullet base when tip leaves the muzzle

def ease_out(t): t = clamp(t); return 1 - (1 - t) ** 3
def ease_in(t): t = clamp(t); return t ** 2.2

def slide_s(f):
    if f < T_BACK[0]: return 0.0
    if f < T_HOLD and f <= T_BACK[1]: return SLIDE_TRAVEL * ease_out(lin(f, *T_BACK))
    if f < T_RET[0]: return SLIDE_TRAVEL
    return SLIDE_TRAVEL * (1 - ease_in(lin(f, *T_RET)))

def bullet_x(f):
    u = lin(f, *T_BUL)
    if f <= T_BUL[1]:
        return BUL_BASE0 + (BUL_EXIT - BUL_BASE0) * u ** 1.3
    v = (BUL_EXIT - BUL_BASE0) * 1.3 / (T_BUL[1] - T_BUL[0])
    return BUL_EXIT + v * (f - T_BUL[1])

# case ejection: find frame where slide passes s=2.7
F_EJECT = next(f for f in range(T_BACK[0], T_BACK[1] + 1) if slide_s(f) >= 2.7)

def kf(obj, path, frame):
    obj.keyframe_insert(path, frame=frame)

for f in range(1, F_END + 1):
    s = slide_s(f)
    slide_rig.location = (-s, 0, 0); kf(slide_rig, 'location', f)

    # barrel: travels 0.4 with the slide, then tilts (breech drops)
    b = min(s, 0.4)
    barrel_pivot.location = (17.6 - b, 0, BORE)
    barrel_pivot.rotation_euler = (0, -math.radians(0.75) * clamp((s - 0.4) / 0.5), 0)
    kf(barrel_pivot, 'location', f); kf(barrel_pivot, 'rotation_euler', f)

    # trigger + bar
    pull = ramp(f, *T_PULL) * (1 - ramp(f, *T_TREL))
    trig_pivot.rotation_euler = (0, math.radians(17) * pull, 0); kf(trig_pivot, 'rotation_euler', f)
    drop = ramp(f, *T_DROP) * (1 - ramp(f, T_TREL[0] + 6, T_TREL[1]))
    bar_back = 0.42 * pull
    bar_pivot.location = (9.4 - bar_back, -1.06, -1.7)
    bar_pivot.rotation_euler = (0, -math.radians(3.6) * drop, 0)
    kf(bar_pivot, 'location', f); kf(bar_pivot, 'rotation_euler', f)

    # striker (relative to slide)
    if f < T_DROP[1]:
        tip = STRIKER_REST - 0.40 * ramp(f, *T_PULL)
    elif f < T_FIRE[1]:
        tip = lerp(STRIKER_REST - 0.40, XB + 0.05, lin(f, T_DROP[1], T_FIRE[1]) ** 2)
    elif f < T_RET[1] - 6:
        tip = XB + 0.05
    else:
        tip = lerp(XB + 0.05, STRIKER_REST, ramp(f, T_RET[1] - 6, T_RET[1]))
    striker.location = (tip, 0, BORE); kf(striker, 'location', f)
    collar = tip - 1.67
    striker_spring.scale = ((collar - SPR_FIX), 1, 1); kf(striker_spring, 'scale', f)
    recoil_spring.scale = ((ROD_X1 - s - ROD_X0), 1, 1); kf(recoil_spring, 'scale', f)

    # bullet
    bx = bullet_x(f)
    bullet.location = (bx, 0, BORE)
    bullet.hide_render = bx > 70
    kf(bullet, 'location', f); bullet.keyframe_insert('hide_render', frame=f)

    # propellant gas column behind the bullet
    g_on = T_FIRE[1] <= f
    gas_len = clamp(bx - (XB + CASE_L - 0.05), 0.001, XM - (XB + CASE_L - 0.05))
    gas.scale = (gas_len if g_on else 0.001, 1 if g_on else 0.01, 1 if g_on else 0.01)
    kf(gas, 'scale', f)
    gas.hide_render = not (T_FIRE[1] <= f < T_BUL[1] + 3)
    gas.keyframe_insert('hide_render', frame=f)

    # chambered case: extracted with the slide, then ejected to the right (-Y, toward camera)
    if f < F_EJECT:
        cx = XB - s; pos = Vector((cx, 0, BORE)); rot = (0, 0, 0)
    else:
        t = f - F_EJECT
        p0 = Vector((XB - slide_s(F_EJECT), 0, BORE))
        pos = p0 + Vector((-0.12 * t, -1.05 * t, 0.55 * t - 0.028 * t * t))
        rot = (math.radians(9 * t), math.radians(-6 * t), math.radians(-31 * t))
    chamber_case.location = pos; chamber_case.rotation_euler = rot
    chamber_case.hide_render = f > F_EJECT + 40
    kf(chamber_case, 'location', f); kf(chamber_case, 'rotation_euler', f); chamber_case.keyframe_insert('hide_render', frame=f)

    # magazine: top round is stripped & chambered while the slide returns, stack rises
    breech = XB - s
    p = clamp((breech - 3.8) / (XB - 3.8)) if f >= T_RET[0] else 0.0
    for i, r in enumerate(rounds):
        if i == 0:
            P0 = mag_pos(0)
            pp = smooth(p)
            r.location = (lerp(P0.x, XB, p), lerp(P0.y, 0, pp), lerp(P0.z, BORE, pp))
            r.rotation_euler = (0, -math.radians(14) * math.sin(math.pi * p), 0)
            kf(r, 'rotation_euler', f)
        else:
            Pa, Pb = mag_pos(i), mag_pos(i - 1)
            r.location = Pa.lerp(Pb, smooth(p))
        kf(r, 'location', f)

    # muzzle flash + comp jets
    fl = clamp(1 - abs(f - (T_BUL[1] + 2)) / 9.0)
    fl = fl ** 1.5
    flash.scale = (max(fl, 0.001), max(fl ** 0.7, 0.001), max(fl ** 0.7, 0.001))
    flash.rotation_euler = (math.radians(f * 23), 0, 0)
    kf(flash, 'scale', f); kf(flash, 'rotation_euler', f)
    flash.hide_render = fl <= 0.002; flash.keyframe_insert('hide_render', frame=f)
    cf = clamp(1 - abs(f - (T_BUL[1] - 2)) / 7.0) ** 1.5
    comp_flash.scale = (max(cf, 0.001),) * 3; kf(comp_flash, 'scale', f)
    comp_flash.hide_render = cf <= 0.002; comp_flash.keyframe_insert('hide_render', frame=f)
    flash_light.data.energy = 0.15 * fl + 0.02 * cf
    flash_light.data.keyframe_insert('energy', frame=f)
    pl = clamp(1 - abs(f - T_FIRE[1]) / 5.0)
    prime_light.data.energy = 0.012 * pl
    prime_light.data.keyframe_insert('energy', frame=f)

    # section fade: near halves fade + drift toward camera
    vis = 1 - ramp(f, *T_FADE) + ramp(f, *T_FADEIN)
    for n in OPACITY_NODES:
        n.outputs[0].default_value = vis
        n.outputs[0].keyframe_insert('default_value', frame=f)
    for o in NEAR:
        if 'base_y' not in o: o['base_y'] = o.location.y
        o.location.y = o['base_y'] - 3.0 * (1 - vis)
        kf(o, 'location', f)
        o.hide_render = vis < 0.01; o.keyframe_insert('hide_render', frame=f)

# ----------------------------------------------------------------- camera path (cm, then *0.01)
C = Vector((8.5, 0, -3.6))
def cam_state(f):
    keys = [  # frame, azimuth(deg), elevation(deg), distance, target
        (1,   55, 14, 82, C),
        (70, -90,  4, 88, C),
        (100, -92, 4, 84, C),
        (125, -96, 6, 50, Vector((5.8, 0, -0.9))),
        (172, -95, 6, 48, Vector((5.6, 0, -0.4))),
        (200, -92, 4, 46, Vector((9.5, 0, 0.6))),
        (240, -88, 3, 50, Vector((17.0, 0, 1.0))),
        (250, -88, 3, 56, Vector((18.5, 0, 1.0))),
        (272, -92, 5, 80, Vector((9.5, 0, -3.2))),
        (305, -92, 5, 80, Vector((9.5, 0, -3.2))),
        (352, -90, 6, 84, C),
        (450, -30, 14, 58, C + Vector((1.5, 0, 0.8))),
    ]
    for (fa, aa, ea, da, ta), (fb, ab, eb, db, tb) in zip(keys, keys[1:]):
        if fa <= f <= fb:
            t = smooth((f - fa) / (fb - fa))
            return lerp(aa, ab, t), lerp(ea, eb, t), lerp(da, db, t), ta.lerp(tb, t)
    return keys[-1][1:]

for f in range(1, F_END + 1):
    az, el, d, tg = cam_state(f)
    az, el = math.radians(az), math.radians(el)
    pos = tg + Vector((math.cos(az) * math.cos(el), math.sin(az) * math.cos(el), math.sin(el))) * d
    cam.location = pos * 0.01; target.location = tg * 0.01
    kf(cam, 'location', f); kf(target, 'location', f)

# linear interpolation everywhere (we key every frame)
def set_linear(idblock):
    ad = getattr(idblock, 'animation_data', None)
    if not ad or not ad.action: return
    try:
        fcs = ad.action.fcurves
    except AttributeError:
        fcs = [fc for layer in ad.action.layers for strip in layer.strips for cb in strip.channelbags for fc in cb.fcurves]
    for fc in fcs:
        for k in fc.keyframe_points:
            k.interpolation = 'CONSTANT' if 'hide' in fc.data_path else 'LINEAR'
for o in bpy.data.objects: set_linear(o)
for m in bpy.data.materials:
    if m.node_tree: set_linear(m.node_tree)
for l in bpy.data.lights: set_linear(l)

# ================================================================== RENDER SETTINGS
r = scene.render
r.engine = 'CYCLES'
r.resolution_x, r.resolution_y = 810, 1440
r.film_transparent = True
r.use_motion_blur = False; r.use_persistent_data = True
cy = scene.cycles
cy.samples = 20; cy.use_denoising = True
cy.max_bounces = 6; cy.transparent_max_bounces = 24
cy.use_adaptive_sampling = True
try: cy.denoiser = 'OPENIMAGEDENOISE'
except Exception: pass
scene.view_settings.view_transform = 'AgX'
try: scene.view_settings.look = 'AgX - Medium High Contrast'
except Exception: pass
r.image_settings.file_format = 'PNG'; r.image_settings.color_mode = 'RGBA'
scene.frame_set(1)

os.makedirs(os.path.dirname(OUT), exist_ok=True)
bpy.ops.wm.save_as_mainfile(filepath=OUT)
print("saved", OUT, "eject frame", F_EJECT)
