"""Export the static Glock 18 model (frame 1, assembled) to model/glock18.glb."""
import bpy, os
here = os.path.dirname(os.path.abspath(__file__))
bpy.ops.wm.open_mainfile(filepath=os.path.join(here, "..", "model", "glock18.blend"))
sc = bpy.context.scene; sc.frame_set(1)
skip = {"MuzzleFlash", "CompFlash", "Gas", "FlashLight", "PrimerLight"}
for o in bpy.data.objects: o.select_set(False)
root = bpy.data.objects["Glock18"]
for o in root.children_recursive:
    if o.name not in skip and o.type in {'MESH', 'CURVE', 'EMPTY'}: o.select_set(True)
root.select_set(True)
bpy.ops.export_scene.gltf(filepath=os.path.join(here, "..", "model", "glock18.glb"),
                          use_selection=True, export_animations=False, export_apply=True)
