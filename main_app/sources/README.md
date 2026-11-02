# 統合開発用の既存ソース

このフォルダは統合開発用のコピー。元の作業ツリーと実機のコードは変更していない。

- collision_prediction: car_program2 ver32 / 799c8f1 の追跡対象ファイルを基に、車線逸脱 Alert の左右を構造化して返す修正を追加。モデル等のGit管理外の資産は含まない。
- dashcam: dashcam_rust_viewer_layout main / 5b495b9 のコピー。
- video_viewer: function_of_transfer_movies main / 682dd33 を基に動画配信を64 KiBずつの分割読み込みに変更。全体・範囲配信のテストを追加したが、Macの開発ツール不足でビルドとテストは未完了。実機または対応環境で検証する。

各ソースは独立しており、まだ統合アプリとして起動できない。実機のバージョン・設定と資産を確認してから統合する。
