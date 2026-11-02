# CMS-V43BK 暗所 FPS 調査（2026-10-30）

## 到達点

暗所で実際に新しく取得する画像を30 FPSに戻す方法は、今回の調査でも確立できなかった。アプリ・AI処理を経由しない取得でも約16.7 FPSであり、入力の制限が残る。カメラ内部の低照度動作やファームウェアの制御を有力な候補とするが、特定の内部処理が原因であるとは断定しない。

同じ画像を繰り返して表示FPSだけを30にする変更は行っていない。補間による合成画像も新たな観測情報を増やさない。

## これまでの観測と今回の切り分け

- 実アプリで照明あり29.9 FPS・実時間比100%、暗所約16.7 FPSを観測。同じカメラを動作させたまま明暗を変えると入力・表示が連動して変化した。照度をluxで測定した試験ではない。
- 暗所でもYOLO・CPU車線解析はそれぞれ約15回/秒を維持。視認性補正の切替はFPSを改善しなかった。
- カメラ単体、320×240、30 FPS指定、OpenCV/V4L2でも約16.7 FPS。YOLO・車線・Qt描画を外しても暗所の入力制限が残った。
- 従前のYUYV/MJPEG、解像度、バッファ数、露出、ゲイン、逆光補正の比較でも、暗所の安定した30 FPSは得られていない。
- 今回は手動露出と電源周波数を組み合わせ、取得開始後にも設定を適用して比較した。約3秒安定待ち後、各約5秒取得。長時間試験ではない。

| 条件 | 取得FPS | フレーム画素平均の概数 |
|---|---:|---:|
| 自動露出、50 Hz | 16.69 | 11.88 |
| 手動露出10 ms、50 Hz | 16.68 | 11.82 |
| 手動露出10 ms、周波数補正なし | 14.99 | 6.21 |
| 手動露出5 ms、周波数補正なし | 15.00 | 6.18 |
| 手動露出20 ms、周波数補正なし | 14.99 | 6.18 |
| 手動露出10 ms、60 Hz | 15.00 | 6.21 |

画素平均は照度の測定値ではない。設定の読み戻しは実際のセンサー積分時間を証明しない。この結果から「露出を短くするだけで直る」とは言えない。

- 明るさ設定を15、0、-32、-64、63と変えても約16.69 FPS。画像の数値上の明るさは変化したが入力速度は改善しなかった。
- Linux UVC統計の取得時点では672フレーム、322998パケット、errors=0、invalid=0。空パケットはあるが、それ自体を転送破損とは解釈しない。この計測ではUSB転送エラーがFPS低下の原因である証拠はない。

## USBレベルの確認

- 製品文字列: HD webcam-CMS-V43BK / AONI
- VID:PID = 1bcf:2281、bcdDevice=0.14、UVC=1.00
- Camera Terminalの対応ビット: AE_MODEとEXPOSURE_ABSOLUTE。AE_PRIORITYは広告されていない。
- AE_PRIORITY（selector 3）に対しUSBでGET_INFO/GET_CURを直接送ってもLIBUSB_ERROR_PIPE。標準の可変FPS禁止制御を、この個体で使えるとは確認できなかった。
- USB直読のため一時的にカーネルドライバーを切り離した後、再接続済み。アプリも再起動済み。
- メーカー拡張XUは存在する。LinuxはXUを利用者空間から制御できるが、項目の意味はメーカー依存である。
  - unit 3 GUID: 7d5a1d99-5b32-428b-8cad-671b8a65f37a
  - unit 6 GUID: 28f03370-6311-4a2e-ba2c-6890eb334016
- GET_INFO/GET_LEN/GET_CUR等で対応範囲を調べた。拡張項目にはレジスターやファームウェアへのアクセスと思われるものが含まれるため、番号だけから低照度スイッチを推測して書き換えてはいない。

## 公式配布ドライバーの静的調査

Microsoft Update Catalog配布のSunplusIT 3.5.18.23をダウンロードし、実行・インストールせず内容を調査した。これはCMS-V43BK専用ドライバーではない。

- 設定ファイルにLowLight、ImageQuality、Speed priority、Balance、Image quality priorityが存在する。
- VCamPPage_x64.dllには、このカメラと同じunit 3のXU GUIDが含まれる。
- 同じGUIDだけでは項目・レジスターの互換性を証明できない。
- 静的解析ではXU selector 2が16ビットのアドレス指定、selector 3が1バイトのデータアクセスとして使用される経路を確認した。
- ドライバー中のImageQuality経路には内部アドレス0x250c/0x250dへの書込経路があるが、この個体の速度優先設定として使えるかは未確認。
- 読出経路の確認として、selector 2の元のアドレス指定を退避し、0x2000、0x250c、0x250dを読んだところ各00だった。最後に元のアドレス指定0020へ復帰。selector 3へのデータ書込はしていない。
- 対応が確定していないため、アプリへのメーカー拡張制御の実装は行っていない。

調査用のWindows配布物はMacの/tmpに保管しただけで、Piに導入していない。OS、カーネル、ファームウェア更新もしていない。

## 次の判断に必要な情報

1. CMS-V43BKの可変フレームレートを止める正式な制御方法があるか。
2. このハードウェア・ファームウェアで低照度モード無効化／速度優先が利用できるか。
3. Linuxから使えるXUのunit、selector、値、適用タイミング、復元方法。
4. 手動露出設定を読み戻せても暗所約16.7 FPSのままである動作が仕様か、不具合か。
5. 対応ファームウェア更新の有無と、更新せずに利用できる回避策。

正式な対応が分かれば、暗所で取得FPS・画素の明るさ・検出結果・結果の遅延を比較し、効果がある場合のみアプリの明示的な設定として導入する。CMS-V43BKの仕様は最低照度30 Lux以上・最大30 FPSであり、暗所30 FPSを保証するものとは読めない。ただし今回の実測照度は不明なので、仕様外と断定しない。

## 復元状態

通常のカメラ設定はauto_exposure=3、exposure_time_absolute=166、gain=16、power_line_frequency=1、brightness=15へ復元。アプリはPiで再起動済みで、調査終了時点ではカメラ入力停止状態。アプリコードの変更、コミット、pushは行っていない。

## 参照

- サンワサプライ仕様: https://www.sanwa.co.jp/product/syohin?code=CMS-V43BK
- Linux露出制御: https://www.kernel.org/doc/html/latest/userspace-api/media/v4l/ext-ctrls-camera.html
- Linux UVC拡張制御: https://www.kernel.org/doc/html/latest/userspace-api/media/drivers/uvcvideo.html
- Microsoft公式配布一覧: https://www.catalog.update.microsoft.com/Search.aspx?q=SunplusIT%203.5.18.23
- 調べた公式配布物: https://catalog.s.download.windowsupdate.com/d/msdownload/update/driver/drvs/2017/11/489ea242-ec61-41fc-9929-19d0ffcdeff1_403f76c5ce54ba250ec33f068d405940aee1e021.cab
- メーカー問い合わせ窓口: https://www.sanwa.co.jp/support/support_regi/index.html?inq_mode=products&sku=CMS-V43BK&syohin_f=True
