"""Smoke-test 3D scene: a mannequin staring at a glowing price tag.
Run:  blender -b -P scene_test.py -- OUT.mp4 WIDTH HEIGHT SECONDS SAMPLES
"""
import sys, math
import bpy

argv = sys.argv[sys.argv.index("--") + 1:]
OUT, W, H, SECONDS, SAMPLES = argv[0], int(argv[1]), int(argv[2]), float(argv[3]), int(argv[4])
FPS = 24
FRAMES = max(24, int(round(SECONDS * FPS)))

# ---------- clean ----------
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene


def mat(name, color, rough=0.5, metal=0.0, emit=None, emit_strength=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*color, 1)
    b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metal
    if emit is not None:
        for key in ("Emission Color", "Emission"):
            if key in b.inputs:
                b.inputs[key].default_value = (*emit, 1)
                break
        if "Emission Strength" in b.inputs:
            b.inputs["Emission Strength"].default_value = emit_strength
    return m


def put(obj, m):
    obj.data.materials.append(m)
    return obj


def smooth(obj):
    for p in obj.data.polygons:
        p.use_smooth = True


# ---------- world ----------
world = bpy.data.worlds.new("W")
scene.world = world
world.use_nodes = True
bg = world.node_tree.nodes["Background"]
bg.inputs["Color"].default_value = (0.01, 0.018, 0.04, 1)
bg.inputs["Strength"].default_value = 1.0

# ---------- floor ----------
bpy.ops.mesh.primitive_plane_add(size=40, location=(0, 0, 0))
floor = bpy.context.object
put(floor, mat("floor", (0.02, 0.03, 0.05), rough=0.18, metal=0.0))

# back wall (soft gradient look from lighting)
bpy.ops.mesh.primitive_plane_add(size=30, location=(0, 9, 8), rotation=(math.radians(90), 0, 0))
wall = bpy.context.object
put(wall, mat("wall", (0.03, 0.045, 0.08), rough=0.9))

# ---------- mannequin ----------
body_mat = mat("mannequin", (0.16, 0.18, 0.23), rough=0.35)
fx, fy = -2.0, 1.4


def prim(kind, loc, scale, rot=(0, 0, 0), **kw):
    if kind == "sphere":
        bpy.ops.mesh.primitive_uv_sphere_add(radius=1, location=loc, segments=48, ring_count=24)
    else:
        bpy.ops.mesh.primitive_cylinder_add(radius=1, depth=1, location=loc, vertices=48)
    o = bpy.context.object
    o.scale = scale
    o.rotation_euler = rot
    smooth(o)
    put(o, body_mat)
    return o


figure_parts = [
    prim("sphere", (fx, fy, 1.82), (0.20, 0.22, 0.25)),                       # head
    prim("cyl", (fx, fy, 1.55), (0.07, 0.07, 0.16)),                          # neck
    prim("sphere", (fx, fy, 1.22), (0.30, 0.19, 0.42)),                       # torso
    prim("cyl", (fx - 0.32, fy, 1.20), (0.065, 0.065, 0.62), (0, math.radians(8), 0)),   # arm L
    prim("cyl", (fx + 0.32, fy, 1.20), (0.065, 0.065, 0.62), (0, math.radians(-8), 0)),  # arm R
    prim("cyl", (fx - 0.12, fy, 0.45), (0.09, 0.09, 0.90)),                   # leg L
    prim("cyl", (fx + 0.12, fy, 0.45), (0.09, 0.09, 0.90)),                   # leg R
]
# face the tag (to +X)
fig_root = bpy.data.objects.new("fig_root", None)
scene.collection.objects.link(fig_root)
fig_root.location = (fx, fy, 0)
for p in figure_parts:
    p.parent = fig_root
    p.matrix_parent_inverse = fig_root.matrix_world.inverted()
fig_root.rotation_euler = (0, 0, math.radians(-25))

# ---------- price tag ----------
tag_root = bpy.data.objects.new("tag_root", None)
scene.collection.objects.link(tag_root)
tag_root.location = (0.35, 2.4, 1.75)

bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, 0))
slab = bpy.context.object
slab.scale = (1.5, 0.06, 1.0)
bev = slab.modifiers.new("b", "BEVEL"); bev.width = 0.06; bev.segments = 4
put(slab, mat("tag", (1.0, 0.62, 0.05), rough=0.35, emit=(1.0, 0.45, 0.0), emit_strength=0.9))
slab.parent = tag_root

bpy.ops.mesh.primitive_cylinder_add(radius=0.012, depth=3, location=(0, 0, 2.5))
string = bpy.context.object
put(string, mat("string", (0.8, 0.8, 0.8), rough=0.4))
string.parent = tag_root

curve = bpy.data.curves.new("price", "FONT")
curve.body = "99"
curve.extrude = 0.05
curve.bevel_depth = 0.01
curve.align_x = "CENTER"
curve.align_y = "CENTER"
curve.size = 0.95
txt = bpy.data.objects.new("price", curve)
scene.collection.objects.link(txt)
txt.location = (0, -0.09, 0.0)
txt.rotation_euler = (math.radians(90), 0, 0)
put(txt, mat("ink", (0.05, 0.03, 0.02), rough=0.4))
txt.parent = tag_root

# tag animation: gentle sway + pulse
for f, (rz, sc) in {1: (-4, 1.0), int(FRAMES * 0.25): (4, 1.07), int(FRAMES * 0.5): (-3, 1.0),
                    int(FRAMES * 0.75): (5, 1.07), FRAMES: (-4, 1.0)}.items():
    tag_root.rotation_euler = (0, 0, math.radians(rz))
    tag_root.scale = (sc, sc, sc)
    tag_root.keyframe_insert("rotation_euler", frame=f)
    tag_root.keyframe_insert("scale", frame=f)

# ---------- lights ----------
def area(name, loc, energy, size, color, target):
    d = bpy.data.lights.new(name, "AREA")
    d.energy, d.size, d.color = energy, size, color
    o = bpy.data.objects.new(name, d)
    scene.collection.objects.link(o)
    o.location = loc
    c = o.constraints.new("TRACK_TO"); c.target = target
    c.track_axis, c.up_axis = "TRACK_NEGATIVE_Z", "UP_Y"
    return o


look = bpy.data.objects.new("look", None)
scene.collection.objects.link(look)
look.location = (-0.5, 1.8, 1.4)

area("key", (3.5, -2.5, 3.8), 900, 3.0, (1.0, 0.82, 0.62), look)
area("rim", (-3.5, 5.5, 3.2), 1400, 2.0, (0.35, 0.65, 1.0), look)
area("fill", (-2, -4, 1.5), 120, 4.0, (0.7, 0.8, 1.0), look)
area("tagglow", (0.4, 0.6, 2.2), 260, 1.5, (1.0, 0.6, 0.2), tag_root)

# ---------- camera (slow dolly-in + drift) ----------
cam_d = bpy.data.cameras.new("cam")
cam_d.lens = 38
cam = bpy.data.objects.new("cam", cam_d)
scene.collection.objects.link(cam)
scene.camera = cam
c = cam.constraints.new("TRACK_TO"); c.target = look
c.track_axis, c.up_axis = "TRACK_NEGATIVE_Z", "UP_Y"
cam.location = (2.2, -6.2, 1.9)
cam.keyframe_insert("location", frame=1)
cam.location = (-0.3, -3.6, 1.55)
cam.keyframe_insert("location", frame=FRAMES)
for fc in cam.animation_data.action.fcurves:
    for kp in fc.keyframe_points:
        kp.interpolation = "BEZIER"
        kp.handle_left_type = kp.handle_right_type = "AUTO_CLAMPED"

# ---------- render ----------
scene.render.engine = "CYCLES"
scene.cycles.device = "CPU"
scene.cycles.samples = SAMPLES
scene.cycles.use_denoising = True
try:
    scene.cycles.denoiser = "OPENIMAGEDENOISE"
except Exception:
    pass
scene.cycles.max_bounces = 4
scene.render.resolution_x, scene.render.resolution_y = W, H
scene.render.resolution_percentage = 100
scene.render.fps = FPS
scene.frame_start, scene.frame_end = 1, FRAMES
try:
    scene.view_settings.view_transform = "Filmic"
    scene.view_settings.look = "Medium High Contrast"
except Exception:
    pass
scene.render.image_settings.file_format = "FFMPEG"
scene.render.ffmpeg.format = "MPEG4"
scene.render.ffmpeg.codec = "H264"
scene.render.ffmpeg.constant_rate_factor = "HIGH"
scene.render.filepath = OUT
bpy.ops.render.render(animation=True)
print("RENDER DONE", OUT, FRAMES, "frames")
