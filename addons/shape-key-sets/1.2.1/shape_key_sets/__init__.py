# SPDX-License-Identifier: GPL-3.0-or-later
bl_info = {
    'name': 'Shape Key Sets', 'author': 'Codex', 'version': (1, 2, 1),
    'blender': (4, 2, 0), 'location': 'View3D > Sidebar > Shape Sets',
    'description': 'Save multiple shape key states per object and switch instantly',
    'category': 'Object',
}

import bpy
from bpy.props import BoolProperty, CollectionProperty, FloatProperty, IntProperty, StringProperty


def shape_keys(obj):
    return getattr(getattr(obj, 'data', None), 'shape_keys', None)


def available(obj):
    keys = shape_keys(obj)
    return bool(obj and obj.is_editable and obj.mode == 'OBJECT' and keys
                and keys.is_editable and keys.use_relative and len(keys.key_blocks) > 1)


def targets(context):
    if context.mode != 'OBJECT':
        return []
    return [obj for obj in context.selected_objects if available(obj)]


def refresh(context):
    for area in context.screen.areas if context.screen else ():
        area.tag_redraw()


def isolate(obj):
    # Shape key values belong to the data, not the object. Preserve other users.
    if obj.data.users > 1:
        obj.data = obj.data.copy()


def capture(obj, preset):
    preset.entries.clear()
    for key in shape_keys(obj).key_blocks[1:]:
        item = preset.entries.add()
        item.name = key.name
        item.value = key.value
        item.mute = key.mute
    preset.solo = obj.show_only_shape_key
    preset.active_key = obj.active_shape_key.name if obj.active_shape_key else ''


def common_name(objects, requested):
    base = requested.strip() or 'Set'
    names = {preset.name for obj in objects for preset in obj.sks_presets}
    result, suffix = base, 2
    while result in names:
        result = f'{base} {suffix}'
        suffix += 1
    return result


def save_selected(operator, context):
    objects = targets(context)
    if not objects:
        return {'CANCELLED'}
    name = common_name(objects, operator.set_name)
    for obj in objects:
        preset = obj.sks_presets.add()
        preset.name = name
        capture(obj, preset)
    skipped = len(context.selected_objects) - len(objects)
    operator.report({'INFO'}, f'{len(objects)}個に保存: {name} / スキップ {skipped}個')
    return {'FINISHED'}


class SKS_Entry(bpy.types.PropertyGroup):
    value: FloatProperty()
    mute: BoolProperty()


class SKS_Preset(bpy.types.PropertyGroup):
    entries: CollectionProperty(type=SKS_Entry)
    solo: BoolProperty()
    active_key: StringProperty()


class SKS_Ready:
    @classmethod
    def poll(cls, context):
        return available(context.object)


class SKS_OT_save(bpy.types.Operator):
    bl_idname = 'object.sks_save'
    bl_label = '選択オブジェクトすべてにセット登録'
    bl_description = '選択中の各対象の状態を、オブジェクトごとに同じセット名で登録'
    bl_options = {'REGISTER', 'UNDO'}
    set_name: StringProperty(name='共通セット名', default='Set')

    @classmethod
    def poll(cls, context):
        return bool(targets(context))

    def invoke(self, context, event):
        self.set_name = common_name(targets(context), 'Set')
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        return save_selected(self, context)


class SKS_Indexed(SKS_Ready):
    index: IntProperty(default=-1, options={'SKIP_SAVE'})

    def get_preset(self, context):
        presets = context.object.sks_presets
        return presets[self.index] if 0 <= self.index < len(presets) else None


class SKS_Selected:
    @classmethod
    def poll(cls, context):
        return bool(targets(context))


class SKS_OT_save_selected(SKS_Selected, bpy.types.Operator):
    bl_idname = 'object.sks_save_selected'
    bl_label = '選択オブジェクトの状態をまとめて保存'
    bl_description = '選択中の各オブジェクトに、それぞれの現在の状態を共通名で新規保存'
    bl_options = {'REGISTER', 'UNDO'}
    set_name: StringProperty(name='共通セット名', default='Set')

    def invoke(self, context, event):
        self.set_name = 'Set'
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        return save_selected(self, context)


class SKS_OT_apply(SKS_Selected, bpy.types.Operator):
    bl_idname = 'object.sks_apply'
    bl_label = '選択オブジェクトに同名セットを適用'
    bl_description = '選択中の各オブジェクトで同名セットを適用。該当なし／同名重複はスキップ'
    bl_options = {'REGISTER', 'UNDO'}
    index: IntProperty(default=-1, options={'SKIP_SAVE'})
    set_name: StringProperty(options={'SKIP_SAVE'})

    def execute(self, context):
        name = self.set_name
        if not self.properties.is_property_set('set_name') and context.object:
            presets = context.object.sks_presets
            if 0 <= self.index < len(presets):
                name = presets[self.index].name
            else:
                return {'CANCELLED'}
        if not self.properties.is_property_set('set_name') and self.index < 0:
            return {'CANCELLED'}
        applied = missing = clamped = skipped = 0
        for obj in targets(context):
            matches = [p for p in obj.sks_presets if p.name == name]
            if len(matches) != 1:
                skipped += 1
                continue
            preset = matches[0]
            keys = shape_keys(obj).key_blocks
            saved = {entry.name: entry for entry in preset.entries}
            if not any(k.name in saved for k in keys[1:]):
                skipped += 1
                continue
            missing += len(set(saved) - {k.name for k in keys[1:]})
            isolate(obj)
            keys = shape_keys(obj).key_blocks
            for key in keys[1:]:
                entry = saved.get(key.name)
                value = entry.value if entry else 0.0
                key.value = value
                key.mute = entry.mute if entry else True
                clamped += abs(key.value - value) > 0.00001
            active_index = keys.find(preset.active_key)
            obj.show_only_shape_key = preset.solo and active_index >= 0
            if active_index >= 0:
                obj.active_shape_key_index = active_index
            obj.data.update_tag()
            applied += 1
        refresh(context)
        unsupported = len(context.selected_objects) - len(targets(context))
        skipped += unsupported
        level = 'WARNING' if skipped or missing or clamped else 'INFO'
        self.report({level}, f'適用 {applied}個 / スキップ {skipped}個 / 不在キー {missing} / 範囲制限 {clamped}')
        return {'FINISHED'} if applied else {'CANCELLED'}


class SKS_OT_off(SKS_Selected, bpy.types.Operator):
    bl_idname = 'object.sks_off'
    bl_label = '選択オブジェクトを完全OFF'
    bl_description = '選択中の全対象で値0＋ミュート、単独表示を解除（保存セットは保持）'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        objects = targets(context)
        for obj in objects:
            isolate(obj)
            for key in shape_keys(obj).key_blocks[1:]:
                key.value = 0.0
                key.mute = True
            obj.show_only_shape_key = False
            obj.data.update_tag()
        refresh(context)
        skipped = len(context.selected_objects) - len(objects)
        self.report({'INFO'}, f'完全OFF: {len(objects)}個 / スキップ {skipped}個')
        return {'FINISHED'}


class SKS_OT_on(SKS_Selected, bpy.types.Operator):
    bl_idname = 'object.sks_on'
    bl_label = '選択オブジェクトを全ON'
    bl_description = '選択中の全対象でBasis以外を値1＋ミュート解除、単独表示を解除'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        objects = targets(context)
        clamped = 0
        for obj in objects:
            isolate(obj)
            for key in shape_keys(obj).key_blocks[1:]:
                key.value = 1.0
                key.mute = False
                clamped += abs(key.value - 1.0) > 0.00001
            obj.show_only_shape_key = False
            obj.data.update_tag()
        refresh(context)
        skipped = len(context.selected_objects) - len(objects)
        level = 'WARNING' if clamped else 'INFO'
        self.report({level}, f'全ON: {len(objects)}個 / スキップ {skipped}個 / 値の範囲制限 {clamped}')
        return {'FINISHED'}


class SKS_OT_update(SKS_Indexed, bpy.types.Operator):
    bl_idname = 'object.sks_update'
    bl_label = '現在の状態で上書き'
    bl_description = 'このセットを現在のシェイプキー状態で上書き（元に戻すで復元可能）'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        preset = self.get_preset(context)
        if preset is None:
            return {'CANCELLED'}
        capture(context.object, preset)
        self.report({'INFO'}, f'上書きしました: {preset.name}')
        return {'FINISHED'}


class SKS_OT_remove(SKS_Indexed, bpy.types.Operator):
    bl_idname = 'object.sks_remove'
    bl_label = 'セットを削除'
    bl_description = '保存セットだけを削除。シェイプキー自体は削除しません'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        if self.get_preset(context) is None:
            return {'CANCELLED'}
        context.object.sks_presets.remove(self.index)
        return {'FINISHED'}


class SKS_PT_panel(bpy.types.Panel):
    bl_label = 'シェイプキー セット'
    bl_idname = 'SKS_PT_panel'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Shape Sets'

    def draw(self, context):
        layout = self.layout
        objects = targets(context)
        batch = layout.box()
        batch.label(text=f'選択中: {len(context.selected_objects)}個 / 対象: {len(objects)}個')
        batch.operator('object.sks_save', icon='ADD')
        row = batch.row()
        row.scale_y = 1.4
        row.operator('object.sks_off', icon='HIDE_ON')
        row = batch.row()
        row.scale_y = 1.4
        row.operator('object.sks_on', icon='HIDE_OFF')
        names = sorted({p.name for obj in objects for p in obj.sks_presets})
        if names:
            batch.label(text='各オブジェクトの同名セットを適用')
        for name in names:
            count = sum(sum(p.name == name for p in obj.sks_presets) == 1 for obj in objects)
            row = batch.row()
            row.enabled = count > 0
            row.scale_y = 1.2
            op = row.operator('object.sks_apply', text=f'{name or "(名前なし)"}  ({count}個)', icon='PLAY')
            op.set_name = name
        if not objects:
            batch.label(text='相対シェイプキーのある対象を選択', icon='INFO')
            batch.label(text='オブジェクトモードで操作してください')
        layout.separator()
        obj = context.object
        if not available(obj):
            layout.label(text='個別編集: 対象をアクティブにしてください', icon='INFO')
            return
        layout.label(text=f'個別編集: {obj.name}', icon='OBJECT_DATA')
        for i, preset in enumerate(obj.sks_presets):
            row = layout.row(align=True)
            row.prop(preset, 'name', text='')
            op = row.operator('object.sks_update', text='', icon='FILE_REFRESH')
            op.index = i
            op = row.operator('object.sks_remove', text='', icon='X')
            op.index = i
        if any(obj.data.users > 1 for obj in objects):
            layout.label(text='切替時に共有データを独立化します', icon='DUPLICATE')
        if any(shape_keys(obj).animation_data for obj in objects):
            layout.label(text='アニメーション等で再変化する場合があります', icon='INFO')
        layout.label(text='各オブジェクトのセットを .blend に保存')


CLASSES = (SKS_Entry, SKS_Preset, SKS_OT_save, SKS_OT_save_selected, SKS_OT_apply, SKS_OT_off, SKS_OT_on,
           SKS_OT_update, SKS_OT_remove, SKS_PT_panel)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Object.sks_presets = CollectionProperty(type=SKS_Preset)


def unregister():
    del bpy.types.Object.sks_presets
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)


if __name__ == '__main__':
    register()
