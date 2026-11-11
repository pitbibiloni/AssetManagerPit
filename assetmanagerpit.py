bl_info = {
    "name": "assetmanagerpit",
    "author": "Pit Bibiloni",
    "version": (1, 0, 0),
    "blender": (5, 2, 0),
    "location": "View3D Sidebar / Asset Browser context menu",
    "description": "Asset catalog organizer and automatic FBX/OBJ texture connector",
    "category": "3D View",
}

import bpy
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

BACKGROUND_EDIT_SCRIPT = r"""import bpy
import sys

args = sys.argv
if "--" not in args:
    raise RuntimeError("Asset Catalog Organizer: missing arguments")

args = args[args.index("--") + 1:]
if len(args) < 3:
    raise RuntimeError("Asset Catalog Organizer: invalid arguments")

catalog_uuid = args[0]
marker = args[1]
pairs = args[2:]


def get_datablock(id_type, name):
    mapping = {
        "ACTION": "actions",
        "ARMATURE": "armatures",
        "BRUSH": "brushes",
        "CAMERA": "cameras",
        "COLLECTION": "collections",
        "CURVE": "curves",
        "CURVES": "hair_curves",
        "FONT": "curves",
        "GREASEPENCIL": "grease_pencils_v3",
        "IMAGE": "images",
        "LIGHT": "lights",
        "LIGHT_PROBE": "lightprobes",
        "LATTICE": "lattices",
        "MATERIAL": "materials",
        "MESH": "meshes",
        "META": "metaballs",
        "MOVIECLIP": "movieclips",
        "NODETREE": "node_groups",
        "OBJECT": "objects",
        "PAINT_CURVE": "paint_curves",
        "PALETTE": "palettes",
        "PARTICLE_SETTINGS": "particles",
        "POINTCLOUD": "pointclouds",
        "SCENE": "scenes",
        "SOUND": "sounds",
        "SPEAKER": "speakers",
        "TEXT": "texts",
        "TEXTURE": "textures",
        "VOLUME": "volumes",
        "WORLD": "worlds",
    }

    collection_name = mapping.get(id_type)
    if not collection_name:
        return None

    collection = getattr(bpy.data, collection_name, None)
    return collection.get(name) if collection else None


changed = 0

for i in range(0, len(pairs), 2):
    id_type = pairs[i]
    name = pairs[i + 1]

    datablock = get_datablock(id_type, name)
    if datablock is None:
        continue

    asset_data = getattr(datablock, "asset_data", None)
    if asset_data is None:
        continue

    if asset_data.catalog_id != catalog_uuid:
        asset_data.catalog_id = catalog_uuid
        changed += 1

if changed:
    bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)

with open(marker, "w", encoding="utf-8") as f:
    f.write(str(changed))
"""

def selected_assets(context):
    try:
        assets = list(context.selected_assets)
        if assets:
            return assets
    except Exception:
        pass
    try:
        if context.asset:
            return [context.asset]
    except Exception:
        pass
    return []


def library_roots():
    roots = []
    for lib in bpy.context.preferences.filepaths.asset_libraries:
        try:
            path = bpy.path.abspath(lib.path)
            if path:
                roots.append((os.path.normcase(os.path.abspath(path)),
                              os.path.abspath(path)))
        except Exception:
            pass
    return roots


def library_root_for_asset(asset):
    blend = getattr(asset, "full_library_path", "") or ""
    if not blend:
        return None
    blend = os.path.normcase(os.path.abspath(bpy.path.abspath(blend)))

    matches = []
    for norm_root, root in library_roots():
        try:
            if os.path.commonpath([blend, norm_root]) == norm_root:
                matches.append((len(norm_root), root))
        except ValueError:
            pass

    if matches:
        matches.sort(reverse=True)
        return matches[0][1]

    return os.path.dirname(blend)


def catalog_file_for_asset(asset):
    root = library_root_for_asset(asset)
    return os.path.join(root, "blender_assets.cats.txt") if root else None


def read_catalogs(path):
    result = []
    if not path or not os.path.isfile(path):
        return result

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or line == "VERSION 1":
                continue
            parts = line.split(":", 2)
            if len(parts) == 3:
                uuid, catalog_path, simple_name = [p.strip() for p in parts]
                if uuid and catalog_path:
                    result.append((uuid, catalog_path, simple_name))
    return result


class ASSETCATALOGORGANIZER_OT_assign(bpy.types.Operator):
    bl_idname = "asset_catalog_organizer.assign"
    bl_label = "Assign Assets to Catalog"
    bl_description = "Assign the selected Asset Browser assets to this catalog"

    catalog_id: bpy.props.StringProperty()
    catalog_path: bpy.props.StringProperty()

    @classmethod
    def poll(cls, context):
        return bool(selected_assets(context))

    def invoke(self, context, event):
        assets = selected_assets(context)
        count = len(assets)

        # The operation edits and saves the source .blend file(s) in the
        # background. Give the user a clear warning before starting.
        return context.window_manager.invoke_confirm(
            self,
            event,
            title="Assign Assets to Catalog",
            message=(
                f"This may take a few moments while Blender updates "
                f"the source file(s). Please wait until the operation finishes. "
                f"Continue with {count} asset(s)?"
            ),
            confirm_text="Assign Assets",
        )

    def execute(self, context):
        assets = selected_assets(context)

        if any(getattr(a, "is_online", False) for a in assets):
            self.report({"ERROR"}, "Online/remote assets are not supported in V0.1")
            return {"CANCELLED"}

        groups = {}
        for asset in assets:
            source = getattr(asset, "full_library_path", "") or ""
            if not source:
                continue
            source = os.path.abspath(bpy.path.abspath(source))
            groups.setdefault(source, []).append((asset.id_type, asset.name))

        if not groups:
            self.report({"ERROR"}, "Could not determine source .blend files")
            return {"CANCELLED"}

        blender = bpy.app.binary_path
        if not blender or not os.path.isfile(blender):
            self.report({"ERROR"}, "Could not locate the Blender executable")
            return {"CANCELLED"}

        bg_fd, bg_script = tempfile.mkstemp(prefix="assetmanagerpit_bg_", suffix=".py")
        os.close(bg_fd)
        with open(bg_script, "w", encoding="utf-8") as _bg_file:
            _bg_file.write(BACKGROUND_EDIT_SCRIPT)
        total = 0
        failed = 0

        for source, pairs in groups.items():
            fd, marker = tempfile.mkstemp(prefix="aco_result_", suffix=".txt")
            os.close(fd)

            try:
                cmd = [
                    blender,
                    "--background",
                    "--factory-startup",
                    source,
                    "--python", bg_script,
                    "--",
                    self.catalog_id,
                    marker,
                ]
                for id_type, name in pairs:
                    cmd.extend([id_type, name])

                completed = subprocess.run(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )

                if completed.returncode != 0:
                    failed += 1
                    print("Asset Catalog Organizer:", completed.stdout)
                    continue

                if os.path.isfile(marker):
                    try:
                        with open(marker, "r", encoding="utf-8") as f:
                            total += int(f.read().strip() or "0")
                    except Exception:
                        pass
            finally:
                try:
                    os.remove(marker)
                except OSError:
                    pass

        try:
            os.remove(bg_script)
        except OSError:
            pass

        try:
            bpy.ops.asset.library_refresh()
        except Exception:
            pass

        if failed:
            self.report({"WARNING"}, f"Assigned {total} asset(s); {failed} source file(s) failed. Check the console.")
        else:
            self.report({"INFO"}, f"Assigned {total} asset(s) to {self.catalog_path}")

        return {"FINISHED"}


class ASSETCATALOGORGANIZER_MT_assign(bpy.types.Menu):
    bl_idname = "ASSETCATALOGORGANIZER_MT_assign"
    bl_label = "Assign to"

    def draw(self, context):
        layout = self.layout
        assets = selected_assets(context)

        if not assets:
            layout.label(text="No assets selected", icon="INFO")
            return

        catalog_file = catalog_file_for_asset(assets[0])
        catalogs = read_catalogs(catalog_file)

        if not catalogs:
            layout.label(text="No catalogs found", icon="ERROR")
            return

        layout.label(
            text=f"Assign {len(assets)} asset(s) to:",
            icon="ASSET_MANAGER",
        )
        layout.separator()

        # Blender 5.2 does not give us a reliable way to create dynamic
        # nested submenus from this context menu. Use the complete catalog
        # path instead, e.g. "Materials / rock / large".
        for uuid, path, simple_name in sorted(
            catalogs, key=lambda x: x[1].strip("/").lower()
        ):
            display_path = path.strip("/").replace("/", " / ")
            op = layout.operator(
                "asset_catalog_organizer.assign",
                text=display_path,
                icon="FILE_FOLDER",
            )
            op.catalog_id = uuid
            op.catalog_path = path


def draw_asset_context_menu(self, context):
    if context.area and context.area.type == "FILE_BROWSER":
        if getattr(context.space_data, "browse_mode", None) == "ASSETS":
            if selected_assets(context):
                self.layout.separator()
                self.layout.menu(
                    ASSETCATALOGORGANIZER_MT_assign.bl_idname,
                    text="Assign to",
                    icon="FILE_FOLDER",
                )


classes = (
    ASSETCATALOGORGANIZER_OT_assign,
    ASSETCATALOGORGANIZER_MT_assign,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    if hasattr(bpy.types, "ASSETBROWSER_MT_context_menu"):
        bpy.types.ASSETBROWSER_MT_context_menu.prepend(draw_asset_context_menu)
    else:
        raise RuntimeError("Blender 5.2 Asset Browser context menu not found")


def unregister():
    if hasattr(bpy.types, "ASSETBROWSER_MT_context_menu"):
        try:
            bpy.types.ASSETBROWSER_MT_context_menu.remove(draw_asset_context_menu)
        except Exception:
            pass

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)



IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".tga", ".bmp", ".exr", ".hdr", ".webp"}
MAP_TOKENS = {
    "BASE_COLOR": ["basecolor", "base_color", "base colour", "albedo", "diffuse", "color", "colour", "_dif", "_diff", "_d", "-d"],
    "ROUGHNESS": ["roughness", "rough", "_rgh", "_r"],
    "METALLIC": ["metallic", "metalness", "metal", "_met", "_m"],
    "NORMAL": ["normalgl", "normaldx", "normal_directx", "normal_opengl", "normal", "_nrm", "_nor", "_n"],
    "AO": ["ambientocclusion", "ambient_occlusion", "occlusion", "_ao", "ao"],
    "EMISSION": ["emissive", "emission", "emit", "_em"],
    "ALPHA": ["opacity", "opacitymask", "transparency", "alpha", "_opac", "_a"],
    "HEIGHT": ["displacement", "height", "bump", "_disp", "_hgt"],
}


def normalized(text):
    text = os.path.splitext(os.path.basename(text))[0].lower()
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_")


def detect_map(filepath):
    stem = normalized(filepath)
    parts = set(stem.split("_"))
    # Match common texture suffixes as tokens, not arbitrary substrings
    # (e.g. avoid interpreting "metal" inside an unrelated material name).
    aliases = {
        "BASE_COLOR": {"basecolor", "base_color", "base_colour", "albedo", "diffuse", "diff", "color", "colour", "col", "dif", "diffusecolor", "diffuse_color", "bc", "d"},
        "ROUGHNESS": {"roughness", "rough", "rgh", "roughnessmap", "roughness_map", "r"},
        "METALLIC": {"metallic", "metalness", "metal", "metalnessmap", "metallicmap", "met", "mt", "m"},
        "NORMAL": {"normal", "normalgl", "normaldx", "normal_directx", "normal_opengl", "normalmap", "normal_map", "nrm", "nor", "n"},
        "AO": {"ao", "ambientocclusion", "ambient_occlusion", "occlusion", "occlusionmap"},
        "EMISSION": {"emissive", "emission", "emit", "emissivemap", "emissionmap"},
        "ALPHA": {"opacity", "opacitymask", "transparency", "alpha", "opac", "alphamask"},
        "HEIGHT": {"displacement", "height", "bump", "disp", "hgt", "heightmap"},
    }
    # Test longest aliases first and allow common separator variants.
    for map_type, tokens in aliases.items():
        for token in sorted(tokens, key=len, reverse=True):
            if token in parts or stem.endswith("_" + token) or stem == token:
                if len(token) == 1 and token not in parts:
                    continue
                return map_type
    return None


def material_key(name):
    value = normalized(name)
    suffixes = [token for tokens in MAP_TOKENS.values() for token in tokens]
    for token in sorted(suffixes, key=len, reverse=True):
        token_norm = re.sub(r"[^a-z0-9]+", "_", token.lower()).strip("_")
        if token_norm and value.endswith("_" + token_norm):
            value = value[:-(len(token_norm) + 1)]
            break
    return value.strip("_")


def scan_images(roots):
    found, seen = [], set()
    for root in roots:
        if not root or not os.path.isdir(root):
            continue
        for current, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d.lower() not in {".git", "__pycache__", "node_modules"}]
            for filename in files:
                if Path(filename).suffix.lower() not in IMAGE_EXTENSIONS:
                    continue
                path = os.path.join(current, filename)
                key = os.path.normcase(os.path.abspath(path))
                if key in seen:
                    continue
                seen.add(key)
                map_type = detect_map(filename)
                if map_type:
                    found.append({"path": path, "map_type": map_type, "key": material_key(filename)})
    return found


def score_candidate(material_name, image_info):
    mat_key, img_key = material_key(material_name), image_info["key"]
    if not mat_key or not img_key:
        return 0
    if mat_key == img_key:
        return 100
    if mat_key in img_key or img_key in mat_key:
        return min(len(mat_key), len(img_key)) + 20
    shared = set(mat_key.split("_")) & set(img_key.split("_"))
    shared -= {"material", "mat", "texture", "tex", "map", "default", "instance"}
    return len(shared) * 3 if shared else 0


def load_image(path):
    abs_path = os.path.abspath(path)
    for image in bpy.data.images:
        try:
            if image.filepath and os.path.normcase(os.path.abspath(bpy.path.abspath(image.filepath))) == os.path.normcase(abs_path):
                return image
        except Exception:
            pass
    try:
        return bpy.data.images.load(abs_path, check_existing=True)
    except Exception:
        return None


def find_principled(material):
    if not material.use_nodes:
        material.use_nodes = True
    nodes = material.node_tree.nodes
    principled = next((node for node in nodes if node.type == 'BSDF_PRINCIPLED'), None)
    if principled is None:
        principled = nodes.new("ShaderNodeBsdfPrincipled")
        output = next((node for node in nodes if node.type == 'OUTPUT_MATERIAL'), None)
        if output is None:
            output = nodes.new("ShaderNodeOutputMaterial")
        material.node_tree.links.new(principled.outputs["BSDF"], output.inputs["Surface"])
    return principled


def connect_map(material, principled, image, map_type, stats):
    nodes, links = material.node_tree.nodes, material.node_tree.links
    tex = next((n for n in nodes if n.type == 'TEX_IMAGE' and n.image == image), None)
    if tex is None:
        tex = nodes.new("ShaderNodeTexImage")
        tex.image = image
        tex.label = map_type.replace("_", " ").title()
    tex.image = image
    if map_type == "BASE_COLOR":
        image.colorspace_settings.name = 'sRGB'
        target = principled.inputs.get("Base Color")
        if target:
            links.new(tex.outputs["Color"], target); stats["connected"] += 1
    elif map_type in {"ROUGHNESS", "METALLIC", "ALPHA", "HEIGHT", "AO"}:
        try: image.colorspace_settings.name = 'Non-Color'
        except Exception: pass
        if map_type == "ROUGHNESS":
            target = principled.inputs.get("Roughness")
            if target: links.new(tex.outputs["Color"], target); stats["connected"] += 1
        elif map_type == "METALLIC":
            target = principled.inputs.get("Metallic")
            if target: links.new(tex.outputs["Color"], target); stats["connected"] += 1
        elif map_type == "ALPHA":
            target = principled.inputs.get("Alpha")
            if target: links.new(tex.outputs["Color"], target); stats["connected"] += 1
        elif map_type == "HEIGHT":
            bump = next((n for n in nodes if n.type == 'BUMP' and n.label == 'Auto Texture Connector Bump'), None)
            if bump is None:
                bump = nodes.new("ShaderNodeBump"); bump.label = 'Auto Texture Connector Bump'
            bump.inputs["Strength"].default_value = 0.15
            links.new(tex.outputs["Color"], bump.inputs["Height"])
            normal_input = principled.inputs.get("Normal")
            if normal_input: links.new(bump.outputs["Normal"], normal_input)
            stats["connected"] += 1
        else:
            stats["ao_images"].append(tex)
    elif map_type == "NORMAL":
        try: image.colorspace_settings.name = 'Non-Color'
        except Exception: pass
        normal = next((n for n in nodes if n.type == 'NORMAL_MAP' and n.label == 'Auto Texture Connector Normal'), None)
        if normal is None:
            normal = nodes.new("ShaderNodeNormalMap"); normal.label = 'Auto Texture Connector Normal'
        links.new(tex.outputs["Color"], normal.inputs["Color"])
        target = principled.inputs.get("Normal")
        if target: links.new(normal.outputs["Normal"], target); stats["connected"] += 1
    elif map_type == "EMISSION":
        try: image.colorspace_settings.name = 'sRGB'
        except Exception: pass
        target = principled.inputs.get("Emission Color") or principled.inputs.get("Emission")
        if target: links.new(tex.outputs["Color"], target); stats["connected"] += 1


def connect_ao(material, principled, ao_nodes, stats):
    if not ao_nodes:
        return
    base_socket = principled.inputs.get("Base Color")
    base_link = next((link for link in base_socket.links), None) if base_socket else None
    base_tex = base_link.from_node if base_link and base_link.from_node.type == 'TEX_IMAGE' else None
    if not base_tex:
        return
    ao_tex = ao_nodes[0]
    nodes, links = material.node_tree.nodes, material.node_tree.links
    mix = next((n for n in nodes if n.type == 'MIX_RGB' and n.label == 'Auto Texture Connector AO'), None)
    if mix is None:
        mix = nodes.new("ShaderNodeMixRGB"); mix.label = 'Auto Texture Connector AO'
    mix.blend_type = 'MULTIPLY'; mix.inputs[0].default_value = 1.0
    links.new(base_tex.outputs["Color"], mix.inputs[1]); links.new(ao_tex.outputs["Color"], mix.inputs[2])
    for link in list(base_socket.links):
        if link.from_node == base_tex: links.remove(link)
    links.new(mix.outputs["Color"], base_socket)
    stats["connected"] += 1


def connect_selected_textures(context, folder):
    selected_objects = list(context.selected_objects)
    if isinstance(folder, str):
        roots = [p for p in folder.splitlines() if p and os.path.isdir(p)]
    else:
        roots = [p for p in folder if p and os.path.isdir(p)]
    if not selected_objects or not roots:
        return 0, 0, "Select the imported model and import it from a known folder."
    image_infos = scan_images(roots)
    if not image_infos:
        return 0, 0, "No recognizable texture images found in that folder or its subfolders."
    stats = {"connected": 0, "materials": 0, "ao_images": []}
    used_materials = set()
    for obj in selected_objects:
        if obj.type != 'MESH':
            continue
        for slot in obj.material_slots:
            material = slot.material
            if not material or material.name in used_materials:
                continue
            used_materials.add(material.name); stats["materials"] += 1
            principled = find_principled(material)
            per_mat = {"connected": 0, "ao_images": []}
            for map_type in MAP_TOKENS:
                candidates = [info for info in image_infos if info["map_type"] == map_type]
                if not candidates: continue
                ranked = sorted(candidates, key=lambda info: score_candidate(material.name, info), reverse=True)
                best = ranked[0]; score = score_candidate(material.name, best)
                if score <= 0 and len(candidates) > 1:
                    # If the material name does not identify the texture, prefer
                    # a texture whose filename shares the object's name.
                    object_keys = [material_key(obj.name), material_key(material.name)]
                    ranked_by_object = sorted(
                        candidates,
                        key=lambda info: max((score_candidate(key, info) for key in object_keys), default=0),
                        reverse=True,
                    )
                    object_score = max((score_candidate(key, ranked_by_object[0]) for key in object_keys), default=0)
                    if object_score <= 0:
                        continue
                    best = ranked_by_object[0]
                image = load_image(best["path"])
                if image: connect_map(material, principled, image, map_type, per_mat)
            connect_ao(material, principled, per_mat["ao_images"], per_mat)
            stats["connected"] += per_mat["connected"]
    if stats["connected"]:
        return stats["connected"], stats["materials"], ""
    return 0, stats["materials"], "No maps could be connected. Check the material and texture names."


def import_model_file(context, filepath):
    filepath = bpy.path.abspath(filepath)
    if not os.path.isfile(filepath):
        return False, "The dropped model file could not be found."
    ext = os.path.splitext(filepath)[1].lower()
    before = set(bpy.data.objects)
    try:
        if ext == ".fbx":
            bpy.ops.import_scene.fbx(filepath=filepath)
        elif ext == ".obj":
            bpy.ops.wm.obj_import(filepath=filepath)
        else:
            return False, "Only FBX and OBJ files are supported."
    except Exception as exc:
        return False, f"Import failed: {exc}"
    imported = [obj for obj in bpy.data.objects if obj not in before]
    if imported:
        bpy.ops.object.select_all(action='DESELECT')
        for obj in imported:
            try: obj.select_set(True)
            except Exception: pass
        mesh = next((obj for obj in imported if obj.type == 'MESH'), imported[0])
        context.view_layer.objects.active = mesh
    return True, ""


class ATC_OT_import_model(bpy.types.Operator):
    bl_idname = "atc.import_model"
    bl_label = "Import FBX / OBJ"
    bl_description = "Choose one or more FBX/OBJ files and remember their folder for texture searching"
    filepath: bpy.props.StringProperty(subtype='FILE_PATH')
    directory: bpy.props.StringProperty(subtype='DIR_PATH')
    files: bpy.props.CollectionProperty(type=bpy.types.OperatorFileListElement)
    filter_glob: bpy.props.StringProperty(default="*.fbx;*.obj", options={'HIDDEN'})

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        if self.files:
            filepaths = [os.path.join(self.directory, item.name) for item in self.files]
        elif self.filepath:
            filepaths = [self.filepath]
        else:
            self.report({'ERROR'}, "Select at least one FBX or OBJ file.")
            return {'CANCELLED'}

        imported_objects = []
        errors = []
        source_folders = []
        for filepath in filepaths:
            folder = os.path.dirname(os.path.abspath(bpy.path.abspath(filepath)))
            if folder and folder not in source_folders:
                source_folders.append(folder)
            before = set(bpy.data.objects)
            ok, message = import_model_file(context, filepath)
            if ok:
                imported_objects.extend(obj for obj in bpy.data.objects if obj not in before)
            else:
                errors.append(os.path.basename(filepath) + ": " + message)

        if not imported_objects:
            self.report({'ERROR'}, errors[0] if errors else "No models were imported.")
            return {'CANCELLED'}

        # Remember every source folder, including files dragged from different directories.
        context.scene.atc_texture_folder = "\n".join(source_folders)

        # Select all objects imported in this batch so texture connection handles them together.
        bpy.ops.object.select_all(action='DESELECT')
        for obj in imported_objects:
            try:
                obj.select_set(True)
            except Exception:
                pass
        mesh = next((obj for obj in imported_objects if obj.type == 'MESH'), imported_objects[0])
        context.view_layer.objects.active = mesh

        if errors:
            self.report({'WARNING'}, f"Imported {len(filepaths) - len(errors)} file(s); {len(errors)} failed. See console for details.")
            for error in errors:
                print("Auto Texture Connector - " + error)
        else:
            self.report({'INFO'}, f"Imported {len(filepaths)} file(s).")

        bpy.ops.atc.confirm_textures('INVOKE_DEFAULT')
        return {'FINISHED'}


class ATC_OT_import_model_drop(bpy.types.Operator):
    bl_idname = "atc.import_model_drop"
    bl_label = "Import Model and Connect Textures"
    bl_description = "Import dropped FBX/OBJ files and ask whether to connect their textures"
    filepath: bpy.props.StringProperty(subtype='FILE_PATH')
    directory: bpy.props.StringProperty(subtype='DIR_PATH')
    files: bpy.props.CollectionProperty(type=bpy.types.OperatorFileListElement)

    def execute(self, context):
        if self.files:
            filepaths = [os.path.join(self.directory, item.name) for item in self.files]
        elif self.filepath:
            filepaths = [self.filepath]
        else:
            self.report({'ERROR'}, "No FBX/OBJ files were provided.")
            return {'CANCELLED'}

        imported_objects = []
        source_folders = []
        errors = []
        for filepath in filepaths:
            folder = os.path.dirname(os.path.abspath(bpy.path.abspath(filepath)))
            if folder and folder not in source_folders:
                source_folders.append(folder)
            before = set(bpy.data.objects)
            ok, message = import_model_file(context, filepath)
            if ok:
                imported_objects.extend(obj for obj in bpy.data.objects if obj not in before)
            else:
                errors.append(f"{os.path.basename(filepath)}: {message}")

        if not imported_objects:
            self.report({'ERROR'}, errors[0] if errors else "No models were imported.")
            return {'CANCELLED'}

        context.scene.atc_texture_folder = "\n".join(source_folders)
        bpy.ops.object.select_all(action='DESELECT')
        for obj in imported_objects:
            try:
                obj.select_set(True)
            except Exception:
                pass
        context.view_layer.objects.active = next((obj for obj in imported_objects if obj.type == 'MESH'), imported_objects[0])

        if errors:
            for error in errors:
                print("Auto Texture Connector - " + error)
            self.report({'WARNING'}, f"Imported models with {len(errors)} failure(s). See console.")
        bpy.ops.atc.confirm_textures('INVOKE_DEFAULT')
        return {'FINISHED'}


class ATC_OT_confirm_textures(bpy.types.Operator):
    bl_idname = "atc.confirm_textures"
    bl_label = "Associated Textures"
    bl_description = "Search the model's folder and connect matching texture maps"

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=390)

    def draw(self, context):
        layout = self.layout
        layout.label(text="Do you wish to import associated textures in the folder?")
        folders = [p for p in context.scene.atc_texture_folder.splitlines() if p]
        if folders:
            layout.label(text=f"Searching {len(folders)} source folder(s)", icon='FILE_FOLDER')
        else:
            layout.label(text="Source folder not found", icon='ERROR')
        layout.label(text="The folder and its subfolders will be searched.")

    def execute(self, context):
        connected, materials, message = connect_selected_textures(context, context.scene.atc_texture_folder)
        if connected:
            self.report({'INFO'}, f"Connected {connected} texture maps across {materials} materials")
            return {'FINISHED'}
        self.report({'WARNING'}, message or "No textures were connected.")
        return {'CANCELLED'}


class ATC_FH_model(bpy.types.FileHandler):
    bl_idname = "ATC_FH_model"
    bl_label = "FBX/OBJ with Auto Texture Connector"
    bl_import_operator = "atc.import_model_drop"
    bl_file_extensions = ".fbx;.obj"

    @classmethod
    def poll_drop(cls, context):
        return context.area is not None and context.area.type == 'VIEW_3D'


class ATC_OT_connect_textures(bpy.types.Operator):
    bl_idname = "atc.connect_textures"
    bl_label = "Connect Textures"
    bl_description = "Connect textures from the source folders of the last imported models"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        connected, materials, message = connect_selected_textures(context, context.scene.atc_texture_folder)
        if connected:
            self.report({'INFO'}, f"Connected {connected} texture maps across {materials} materials")
            return {'FINISHED'}
        self.report({'WARNING'}, message or "No textures were connected.")
        return {'CANCELLED'}


class ATC_PT_panel(bpy.types.Panel):
    bl_label = "Texture Connector"
    bl_idname = "ATC_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "AssetManagerPit"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        layout.operator("atc.import_model", text="Import FBX / OBJ", icon='IMPORT')
        layout.operator("atc.connect_textures", text="Connect Textures", icon='NODE_MATERIAL')
        if scene.atc_texture_folder:
            folders = [p for p in scene.atc_texture_folder.splitlines() if p]
            layout.label(text=f"Source folders: {len(folders)}", icon='FILE_FOLDER')
            layout.label(text="Folders and subfolders are searched automatically.")
        else:
            layout.label(text="Drop an FBX/OBJ or import above.", icon='INFO')


classes = (ATC_OT_import_model, ATC_OT_import_model_drop, ATC_OT_confirm_textures, ATC_FH_model, ATC_OT_connect_textures, ATC_PT_panel)


ASSETMANAGERPIT_CLASSES = (
    ASSETCATALOGORGANIZER_OT_assign,
    ASSETCATALOGORGANIZER_MT_assign,
    ATC_OT_import_model,
    ATC_OT_import_model_drop,
    ATC_OT_confirm_textures,
    ATC_FH_model,
    ATC_OT_connect_textures,
    ATC_PT_panel,
)


def register():
    if not hasattr(bpy.types.Scene, "atc_texture_folder"):
        bpy.types.Scene.atc_texture_folder = bpy.props.StringProperty(
            name="Texture Folders",
            description="Source folders of the last imported FBX/OBJ files",
            default="",
        )
    registered = []
    try:
        for cls in ASSETMANAGERPIT_CLASSES:
            bpy.utils.register_class(cls)
            registered.append(cls)
        if hasattr(bpy.types, "ASSETBROWSER_MT_context_menu"):
            bpy.types.ASSETBROWSER_MT_context_menu.prepend(draw_asset_context_menu)
        else:
            raise RuntimeError("Blender 5.2 Asset Browser context menu not found")
    except Exception:
        if hasattr(bpy.types, "ASSETBROWSER_MT_context_menu"):
            try:
                bpy.types.ASSETBROWSER_MT_context_menu.remove(draw_asset_context_menu)
            except Exception:
                pass
        for cls in reversed(registered):
            try:
                bpy.utils.unregister_class(cls)
            except Exception:
                pass
        if hasattr(bpy.types.Scene, "atc_texture_folder"):
            del bpy.types.Scene.atc_texture_folder
        raise


def unregister():
    if hasattr(bpy.types, "ASSETBROWSER_MT_context_menu"):
        try:
            bpy.types.ASSETBROWSER_MT_context_menu.remove(draw_asset_context_menu)
        except Exception:
            pass
    for cls in reversed(ASSETMANAGERPIT_CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
    if hasattr(bpy.types.Scene, "atc_texture_folder"):
        del bpy.types.Scene.atc_texture_folder


if __name__ == "__main__":
    register()
