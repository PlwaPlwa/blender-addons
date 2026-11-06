# SPDX-License-Identifier: GPL-3.0-or-later
bl_info = {
    'name': 'Uniform Strip Width', 'author': 'Blender Add-on Factory',
    'version': (1, 4, 1), 'blender': (5, 0, 0),
    'location': '3Dビュー > サイドバー > USW',
    'description': '既存エッジ上をスライドして四角形帯の幅を均一化',
    'category': 'Mesh',
}

import math
import bpy
import bmesh
from mathutils import Matrix
from bpy.props import EnumProperty, PointerProperty, FloatProperty, StringProperty


class StripError(Exception):
    pass


def editable(context):
    obj = context.active_object
    return (context.mode == 'EDIT_MESH' and obj is not None and obj.type == 'MESH')


def mesh_context(context):
    if not editable(context):
        raise StripError('メッシュの編集モードで実行してください。')
    obj = context.active_object
    if len(context.objects_in_mode) != 1:
        raise StripError('複数オブジェクトの同時編集には対応していません。')
    if obj.library or obj.override_library or obj.data.library or not obj.is_editable or not obj.data.is_editable:
        raise StripError('リンク・オーバーライド・読み取り専用データは処理できません。')
    if obj.data.users != 1:
        raise StripError('共有メッシュです。先にシングルユーザー化してください。')
    if obj.active_shape_key and obj.active_shape_key.lock_shape:
        raise StripError('編集中のシェイプキーがロックされています。ロックを解除してください。')
    bm = bmesh.from_edit_mesh(obj.data)
    for seq in (bm.verts, bm.edges, bm.faces):
        seq.ensure_lookup_table()
        seq.index_update()
    return obj, bm


def show_warning(context, message):
    """背景実行では通知だけ、GUIでは閉じるまで理由を表示する。"""
    if bpy.app.background or context.window is None:
        return

    def draw(menu, _context):
        for part in message.split('。'):
            if part:
                menu.layout.label(text=part + '。')

    context.window_manager.popup_menu(draw, title='選択内容を確認してください', icon='ERROR')


def strip_pairs(bm, edge, a, b):
    faces = {f for f in bm.faces if f.select}
    if not faces or any(len(f.verts) != 4 or f.hide for f in faces):
        raise StripError('対象の1列の四角形帯だけを面選択してください。')
    if not any(f in faces for f in edge.link_faces):
        raise StripError('選択帯に基準エッジが含まれていません。')
    pairs = {edge: (a, b)}
    queue = [edge]
    visited = set()
    while queue:
        cross = queue.pop()
        va, vb = pairs[cross]
        for face in cross.link_faces:
            if face not in faces:
                continue
            visited.add(face)
            opposite = next(e for e in face.edges if not any(v in cross.verts for v in e.verts))
            oa = next(v for v in opposite.verts if any(va in e.verts and v in e.verts for e in face.edges))
            ob = opposite.other_vert(oa)
            if opposite in pairs:
                if pairs[opposite] != (oa, ob):
                    raise StripError('ねじれた帯または対応の不一致を検出しました。')
            else:
                pairs[opposite] = (oa, ob)
                queue.append(opposite)
    if visited != faces:
        raise StripError('分岐・複数列・不連続な面選択には対応していません。')
    av = [p[0] for p in pairs.values()]
    bv = [p[1] for p in pairs.values()]
    if len(set(av + bv)) != 2 * len(pairs):
        raise StripError('境界の分岐または頂点の重複を検出しました。')
    verts = set(av + bv)
    if any(v.hide for v in verts):
        raise StripError('非表示の頂点が含まれています。')
    if any(sum(f in faces for f in e.link_faces) > 2 for f in faces for e in f.edges):
        raise StripError('選択した帯の内部で面が分岐しています。')
    for side in (set(av), set(bv)):
        rails = {e for f in faces for e in f.edges if all(v in side for v in e.verts)}
        degrees = [sum(v in e.verts for e in rails) for v in side]
        if any(d not in (1, 2) for d in degrees):
            raise StripError('2本の単純な境界を識別できません。')
    return faces, pairs


def selected_strip(obj, bm):
    """選択面から帯の横断方向とA/Bを自動判定。事前記録やモード指定は不要。"""
    for seq in (bm.verts, bm.edges, bm.faces):
        seq.ensure_lookup_table()
        seq.index_update()
    selected = [f for f in bm.faces if f.select]
    if not selected:
        raise StripError('表側の帯の面を選択してから実行してください。')
    if any(len(f.verts) != 4 or f.hide for f in selected):
        raise StripError('表側で1列につながる四角形の面を選択してください。')
    candidates = {}
    for edge in min(selected, key=lambda f: f.index).edges:
        a,b = sorted(edge.verts, key=lambda v: v.index)
        try:
            faces, pairs = strip_pairs(bm, edge, a, b)
        except StripError:
            continue
        key = tuple(sorted(e.index for e in pairs))
        candidates[key] = (faces, pairs)
    if not candidates:
        raise StripError('帯の方向を判定できませんでした。表側で1列につながる面だけを選択してください。')
    # 1面では縦横を区別する接続がないため、平均長の短い辺の組を幅方向とする。
    faces,pairs = min(candidates.values(), key=lambda item:
        (sum((obj.matrix_world @ a.co-obj.matrix_world @ b.co).length
             for a,b in item[1].values())/len(item[1]), min(e.index for e in item[1])))
    edge = min(pairs, key=lambda e: e.index)
    a,b = sorted(edge.verts, key=lambda v: v.index)
    faces,pairs = strip_pairs(bm, edge, a, b)
    return edge,a,b,faces,pairs


def segment_roots(start, end, center, radius):
    direction = end - start
    delta = start - center
    aa = direction.length_squared
    if aa <= 1e-24:
        return []
    bb = 2 * delta.dot(direction)
    cc = delta.length_squared - radius * radius
    disc = bb * bb - 4 * aa * cc
    tol = 1e-12 * max(bb * bb, abs(4 * aa * cc), 1e-24)
    if disc < -tol:
        return []
    root = math.sqrt(max(0.0, disc))
    return [min(1.0, max(0.0, t)) for t in ((-bb-root)/(2*aa), (-bb+root)/(2*aa))
            if -1e-7 <= t <= 1+1e-7]


def normal_position(obj, fixed, move, target_width):
    world = obj.matrix_world
    start, center = world @ move.co, world @ fixed.co
    # 非一様スケール下でも、幾何学的なワールド法線方向に移動する。
    normal = world.to_3x3().inverted().transposed() @ move.normal
    if not all(math.isfinite(x) for x in normal) or normal.length <= 1e-12:
        raise StripError('頂点%dの法線を取得できませんでした。' % move.index)
    normal.normalize()
    delta = start-center
    projection = delta.dot(normal)
    gap = target_width*target_width-delta.length_squared
    root = math.sqrt(max(0.0, projection*projection+gap))
    distance = gap/(root+projection) if projection > 0 else root-projection
    if not math.isfinite(distance) or distance < 0:
        raise StripError('頂点%dを法線方向で目標幅に移動できませんでした。' % move.index)
    return world.inverted() @ (start+normal*distance)


def plan_positions(obj, bm, side, details=None, target_width=None):
    if target_width is not None and (not math.isfinite(target_width) or target_width <= 1e-8):
        raise StripError('先に基準となるエッジの幅を取得してください。')
    if side not in {'A', 'B'}:
        raise StripError('固定側が無効です。')
    edge, a, b, faces, pairs = selected_strip(obj, bm)
    world = obj.matrix_world
    if not all(math.isfinite(x) for row in world for x in row) or abs(world.determinant()) < 1e-15:
        raise StripError('オブジェクトの変換行列が無効です。')
    widths = []
    for va, vb in pairs.values():
        if not all(math.isfinite(x) for vertex in (va, vb) for x in vertex.co):
            raise StripError('対象の帯に無効な座標があります。')
        width = (world @ va.co - world @ vb.co).length
        if not math.isfinite(width) or width <= 1e-8:
            raise StripError('対象の帯に長さゼロまたは極端に短い横断辺があります。')
        widths.append(width)
    target_width = min(widths) if target_width is None else target_width
    proposed = {}
    for cross, pair in pairs.items():
        fixed, move = pair if side == 'A' else pair[::-1]
        start = world @ move.co
        center = world @ fixed.co
        if abs((start-center).length-target_width) <= max(1e-6*target_width, 1e-7):
            proposed[move] = move.co.copy()
            continue
        if (start-center).length < target_width:
            co = normal_position(obj, fixed, move, target_width)
        else:
            # 太い箇所は元の横断辺の線分上を固定側へスライドする。
            solutions = []
            for t in segment_roots(start, center, center, target_width):
                co = move.co.lerp(fixed.co, t)
                solutions.append(((world @ co-start).length_squared, co))
            if not solutions:
                raise StripError('頂点%dのスライド位置を計算できませんでした。' % move.index)
            co = min(solutions, key=lambda item: item[0])[1]
        if abs((world @ co-center).length-target_width) > max(1e-6*target_width, 1e-7):
            raise StripError('数値精度の範囲内で幅を計算できません。')
        proposed[move] = co
    if details is not None:
        details['target_width'] = target_width
    validate_faces(bm, proposed)
    return proposed


def validate_faces(bm, proposed):
    # NGONの内部対角線は形状に応じて変化できるので、個々の三角形の符号を制約にしない。
    affected = {f for v in proposed for f in v.link_faces}
    for face in affected:
        old = [v.co for v in face.verts]
        new = [proposed.get(v, v.co) for v in face.verts]
        old_area = sum((old[i].cross(old[(i+1)%len(old)]) for i in range(len(old))), old[0]*0)
        new_area = sum((new[i].cross(new[(i+1)%len(new)]) for i in range(len(new))), new[0]*0)
        if old_area.length_squared > 1e-24 and (new_area.length_squared <= 1e-24 or old_area.dot(new_area) <= 0):
            raise StripError('移動で面が潰れるか反転します。固定側や基準幅を変更してください。')
        for i in range(len(new)):
            j = (i+1)%len(new)
            if (old[i]-old[j]).length_squared > 1e-24 and (new[i]-new[j]).length_squared <= 1e-24:
                raise StripError('移動で辺が潰れます。固定側や基準幅を変更してください。')


def key_compensation(obj, bm, positions):
    # Basis以外を編集したとき、Blenderが相対参照する子キーへ自動伝播する分を相殺する。
    # Basis編集では標準の伝播を使い、各キーの差分を保つ。
    if not obj.data.shape_keys or not obj.data.shape_keys.use_relative or obj.active_shape_key_index == 0:
        return []
    active = obj.active_shape_key
    layers = []
    for key in obj.data.shape_keys.key_blocks:
        if key == active:
            continue
        cursor = key.relative_key
        visited = {key.name}
        while cursor and cursor.name not in visited:
            if cursor == active:
                layer = bm.verts.layers.shape.get(key.name)
                if layer is not None:
                    layers.append(layer)
                break
            visited.add(cursor.name)
            cursor = cursor.relative_key
    return [(vertex, layer, vertex[layer] - (co-vertex.co))
            for vertex,co in positions.items() for layer in layers]


class USW_Settings(bpy.types.PropertyGroup):
    fixed_side: EnumProperty(name='固定側', items=[('A', 'Fixed Side A', '橙色の端点を含む境界を固定'),
                                                ('B', 'Fixed Side B', '水色の端点を含む境界を固定')], default='A')


class MESH_OT_usw_apply(bpy.types.Operator):
    bl_idname = 'mesh.uniform_strip_apply'
    bl_label = '幅を均一化 / Apply Uniform Width'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return editable(context)

    def execute(self, context):
        try:
            obj, bm = mesh_context(context)
            details = {}
            positions = plan_positions(obj, bm, obj.uniform_strip_width.fixed_side, details)
            compensation = key_compensation(obj, bm, positions)
        except StripError as error:
            self.report({'WARNING'}, str(error))
            show_warning(context, str(error))
            return {'CANCELLED'}
        changed = sum((vertex.co-position).length_squared > 1e-20 for vertex, position in positions.items())
        for vertex, layer, co in compensation:
            vertex[layer] = co
        for vertex, position in positions.items():
            vertex.co = position
        bm.normal_update()
        bmesh.update_edit_mesh(obj.data, loop_triangles=True, destructive=False)
        self.report({'INFO'}, '最短幅 %.6g に統一。%d頂点を移動しました。%s' % (details['target_width'], changed, '既に均一です。' if changed == 0 else ''))
        return {'FINISHED'}


class USW_Reference(bpy.types.PropertyGroup):
    width: FloatProperty(name='取得した幅', default=0, precision=6)
    source: StringProperty(name='取得元')


class MESH_OT_usw_capture_width(bpy.types.Operator):
    bl_idname = 'mesh.uniform_strip_capture_width'
    bl_label = '選択エッジの幅を取得'
    bl_description = '選択した1本の辺のワールド距離を記録。同じオブジェクト・別オブジェクトで使用できます'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return editable(context)

    def execute(self, context):
        try:
            obj = context.active_object
            bm = bmesh.from_edit_mesh(obj.data)
            selected = [edge for edge in bm.edges if edge.select and not edge.hide]
            if len(selected) != 1:
                raise StripError('基準にするエッジを1本だけ選択してください。')
            edge = selected[0]
            width = (obj.matrix_world @ edge.verts[0].co-obj.matrix_world @ edge.verts[1].co).length
            if not math.isfinite(width) or width <= 1e-8:
                raise StripError('長さのあるエッジを選択してください。')
        except StripError as error:
            self.report({'WARNING'}, str(error))
            show_warning(context, str(error))
            return {'CANCELLED'}
        ref = context.scene.uniform_strip_width_reference
        ref.width, ref.source = width, obj.name
        self.report({'INFO'}, '幅 %.6g を取得しました。対象の表側の帯を面選択してください。' % width)
        return {'FINISHED'}


class MESH_OT_usw_apply_reference(bpy.types.Operator):
    bl_idname = 'mesh.uniform_strip_apply_reference'
    bl_label = '取得した幅に合わせる'
    bl_description = '太い箇所はスライド、細い箇所は移動側頂点の正の法線方向に動かします'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return editable(context)

    def execute(self, context):
        try:
            obj, bm = mesh_context(context)
            target = context.scene.uniform_strip_width_reference.width
            positions = plan_positions(obj, bm, obj.uniform_strip_width.fixed_side, target_width=target)
            compensation = key_compensation(obj, bm, positions)
        except StripError as error:
            self.report({'WARNING'}, str(error))
            show_warning(context, str(error))
            return {'CANCELLED'}
        for vertex, layer, co in compensation:
            vertex[layer] = co
        for vertex, co in positions.items():
            vertex.co = co
        bm.normal_update()
        bmesh.update_edit_mesh(obj.data, loop_triangles=True, destructive=False)
        self.report({'INFO'}, '取得した幅 %.6g に合わせました。' % target)
        return {'FINISHED'}


def marker_panel_visible(context):
    """この3DビューのサイドバーでUSWタブを開いている間だけ表示する。"""
    if not editable(context):
        return False
    area, space = context.area, context.space_data
    if area is None or area.type != 'VIEW_3D' or space is None:
        return False
    if not space.show_region_ui or not space.show_gizmo:
        return False
    sidebar = next((region for region in area.regions if region.type == 'UI'), None)
    return sidebar is not None and sidebar.active_panel_category == 'USW'


class VIEW3D_GGT_usw_endpoints(bpy.types.GizmoGroup):
    bl_idname = 'VIEW3D_GGT_usw_endpoints'
    bl_label = '基準エッジのA/B表示'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'
    bl_options = {'3D', 'PERSISTENT'}

    @classmethod
    def poll(cls, context):
        return marker_panel_visible(context)

    def setup(self, context):
        self.markers = []
        for color in ((1.0, 0.3, 0.02), (0.05, 0.7, 1.0)):
            gizmo = self.gizmos.new('GIZMO_GT_move_3d')
            gizmo.draw_style = 'RING_2D'
            gizmo.color = color
            gizmo.alpha = 1.0
            gizmo.color_highlight = color
            gizmo.alpha_highlight = 1.0
            gizmo.scale_basis = 0.22
            gizmo.hide_select = True
            self.markers.append(gizmo)

    def draw_prepare(self, context):
        for gizmo in self.markers:
            gizmo.hide = True
        if not marker_panel_visible(context):
            return
        obj = context.active_object
        try:
            bm = bmesh.from_edit_mesh(obj.data)
            bm.verts.ensure_lookup_table()
            edge, a, b, faces, pairs = selected_strip(obj, bm)
            st = obj.uniform_strip_width
            for gizmo, index, side in zip(self.markers, (a.index, b.index), ('A', 'B')):
                gizmo.hide = False
                gizmo.matrix_basis = Matrix.Translation(obj.matrix_world @ bm.verts[index].co)
                gizmo.scale_basis = 0.30 if st.fixed_side == side else 0.18
        except (StripError, IndexError, ReferenceError):
            for gizmo in self.markers:
                gizmo.hide = True


class VIEW3D_PT_usw(bpy.types.Panel):
    bl_label = 'Uniform Strip Width'
    bl_idname = 'VIEW3D_PT_uniform_strip_width'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'USW'

    def draw(self, context):
        layout = self.layout
        if not editable(context):
            layout.label(text='メッシュの編集モードで使用します。')
            return
        obj = context.active_object
        st = obj.uniform_strip_width
        layout.label(text='目標幅: 選択した帯の最短幅（自動）')
        layout.prop(st, 'fixed_side', expand=True)
        layout.label(text='A = 橙色 / B = 水色（固定側は大きい輪）')
        layout.label(text='丸印はUSWタブを表示している間だけ表示。')
        try:
            bm = bmesh.from_edit_mesh(obj.data)
            edge,a,b,faces,pairs = selected_strip(obj,bm)
            layout.label(text='端点番号: A=%d / B=%d' % (a.index,b.index))
        except StripError:
            layout.label(text='端点番号: 面の選択後に自動表示')
        layout.label(text='対象の表面の帯を面選択してください。')
        layout.operator('mesh.uniform_strip_apply')


class VIEW3D_PT_usw_reference(bpy.types.Panel):
    bl_label = '別のエッジの幅に合わせる'
    bl_idname = 'VIEW3D_PT_uniform_strip_width_reference'
    bl_parent_id = 'VIEW3D_PT_uniform_strip_width'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        ref = context.scene.uniform_strip_width_reference
        layout.operator('mesh.uniform_strip_capture_width')
        layout.label(text='取得した幅: %.6g' % ref.width)
        if ref.source:
            layout.label(text='取得元: ' + ref.source)
        layout.label(text='固定側は上のA/Bを使用します。')
        layout.label(text='細い箇所は頂点の法線方向に拡幅します。')
        layout.operator('mesh.uniform_strip_apply_reference')


classes = (USW_Settings, USW_Reference, MESH_OT_usw_apply, MESH_OT_usw_capture_width, MESH_OT_usw_apply_reference, VIEW3D_PT_usw, VIEW3D_PT_usw_reference, VIEW3D_GGT_usw_endpoints)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Object.uniform_strip_width = PointerProperty(type=USW_Settings)
    bpy.types.Scene.uniform_strip_width_reference = PointerProperty(type=USW_Reference)


def unregister():
    del bpy.types.Scene.uniform_strip_width_reference
    del bpy.types.Object.uniform_strip_width
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == '__main__':
    register()
