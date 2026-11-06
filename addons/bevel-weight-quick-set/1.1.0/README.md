# Bevel Weight Quick Set

選択エッジのベベルウェイトを右クリックメニューから1.0または0.0に設定できるアドオンです。

## 主な機能

- エッジ選択モードの右クリックメニューに1.0と0.0の設定項目を追加します。
- ダイアログや数値入力なしで、選択エッジだけを即時変更します。
- 未選択エッジの既存ウェイトは保持します。
- 必要なEDGE/FLOATのbevel_weight_edge属性がなければ作成します。
- 複数オブジェクトの同時編集に対応し、共有メッシュは一度だけ処理します。
- Blender標準のUndoを利用する宣言を持ちます。

## インストール

BlenderのPreferences → Add-ons → メニュー → Install from Diskで配布ZIPを選び、有効化します。 単体.pyファイルを配布している場合は、その.pyを解凍せず同じメニューで選択しても導入できます。

## 使い方

1. 配布されているbevel_weight_one.pyを保存します。
2. PreferencesのAdd-onsでInstall from Diskを選び、bevel_weight_one.pyをインストールして有効化します。
3. メッシュを編集モードにし、エッジ選択を有効にして対象エッジを選びます。
4. 3Dビューを右クリックし、Set Bevel Weight to 1.0またはSet Bevel Weight to 0.0を選びます。

## 対応環境

設定上の最低バージョン: Blender 5.0.0。実際の確認環境はTEST_RESULTS.jsonを参照してください。

## 制約・未検証

- 5.0.0のGUIメニュー・Undo確認はユーザー提供の検証記録に基づきます。
- 5.2.2 LTSは今回バックグラウンドで機能を検証し、実際のGUIクリック・Undoは未検証です。
- WindowsとLinuxは今回未検証です。
- メニューとツールチップは英語です。
- 属性を新規作成した場合、未選択エッジの値は新規属性の既定値0.0になります。
- ウェイトを変更する機能であり、ベベル形状自体を追加するものではありません。

## ライセンス

GPL-3.0-or-later

## 不具合報告・ご要望

[GitHub Issues](https://github.com/PlwaPlwa/blender-addons/issues/new)へ、アドオンとBlenderのバージョン、OS、再現手順、期待した動作と実際の動作をお知らせください。制作データや個人情報の公開にはご注意ください。
