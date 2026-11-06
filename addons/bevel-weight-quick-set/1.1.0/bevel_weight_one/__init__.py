# SPDX-License-Identifier: GPL-3.0-or-later
"""Set selected edit-mode edges' bevel weights to 1.0 or 0.0 in Blender 5.0."""

bl_info = {
    "name": "Bevel Weight Quick Set",
    "author": "Codex",
    "version": (1, 1, 0),
    "blender": (5, 0, 0),
    "location": "3D View > Edit Mode > Edge Context Menu",
    "description": "Set selected edge bevel weights to 1.0 or 0.0 immediately",
    "category": "Mesh",
}

import bpy
import bmesh

ATTRIBUTE = "bevel_weight_edge"


class BevelWeightMixin:
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return (context.mode == 'EDIT_MESH'
                and context.edit_object is not None
                and context.tool_settings.mesh_select_mode[1])

    def execute(self, context):
        targets = []
        for obj in context.objects_in_mode_unique_data:
            if obj.type != 'MESH':
                continue
            mesh = obj.data
            bm = bmesh.from_edit_mesh(mesh)
            selected = [edge for edge in bm.edges if edge.select]
            if not selected:
                continue
            attribute = mesh.attributes.get(ATTRIBUTE)
            if attribute and (attribute.domain != 'EDGE'
                              or attribute.data_type != 'FLOAT'):
                self.report({'ERROR'}, "bevel_weight_edge must be an EDGE/FLOAT attribute")
                return {'CANCELLED'}
            targets.append((mesh, bm))

        if not targets:
            return {'CANCELLED'}
        for mesh, bm in targets:
            layer = bm.edges.layers.float.get(ATTRIBUTE)
            if layer is None:
                layer = bm.edges.layers.float.new(ATTRIBUTE)
            for edge in bm.edges:
                if edge.select:
                    edge[layer] = self.weight
            bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)
        return {'FINISHED'}


class MESH_OT_bevel_weight_one(BevelWeightMixin, bpy.types.Operator):
    bl_idname = "mesh.bevel_weight_one"
    bl_label = "Set Bevel Weight to 1.0"
    bl_description = "Set selected edges' bevel weights to 1.0"
    weight = 1.0


class MESH_OT_bevel_weight_zero(BevelWeightMixin, bpy.types.Operator):
    bl_idname = "mesh.bevel_weight_zero"
    bl_label = "Set Bevel Weight to 0.0"
    bl_description = "Set selected edges' bevel weights to 0.0"
    weight = 0.0


CLASSES = (MESH_OT_bevel_weight_one, MESH_OT_bevel_weight_zero)


def draw_context_menu(self, context):
    if MESH_OT_bevel_weight_one.poll(context):
        self.layout.separator()
        for cls in CLASSES:
            self.layout.operator(cls.bl_idname, text=cls.bl_label)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.VIEW3D_MT_edit_mesh_context_menu.append(draw_context_menu)


def unregister():
    bpy.types.VIEW3D_MT_edit_mesh_context_menu.remove(draw_context_menu)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
