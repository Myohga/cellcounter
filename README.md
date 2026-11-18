# cellcounter

免疫染色画像（.czi）で、細胞のマーカー陽性判定を行うソフトです。
核を自動で検出し、マーカーごとに陽性を自動判定し、人が × を足す・消すことで確定します。

0.1.0 は判定法の検証が済むまでの開発版です。

## 導入（Python の入っていない PC から）

Windows 10 / 11（64 ビット）の PC を想定しています。
始める前に、インターネットにつながっていることと、C ドライブに 10 GB 以上（GPU を使うときは 15 GB 以上）の空きがあることを確かめてください。
管理者の権限は、GPU のドライバーを入れるとき以外は要りません。

入れ方は 2 通りあります。どちらも PC ごとに 1 回だけ行い、全部で 30 分〜1 時間ほどかかります（多くはダウンロードの待ち時間です）。

- **install.bat で入れる（おすすめ）**: ファイルを 1 つダウンロードしてダブルクリックするだけです。下の手順 1〜5 を自動で行います。
- **手で入れる**: 下の手順 1〜5 を、コマンドを打って行います。install.bat が途中で止まって直せないときなどに使います。

どちらで入れたときも、最後に手順 6 で起動を確かめます。

### install.bat で入れる（おすすめ）

1. NVIDIA の GPU がある PC では、先に NVIDIA のドライバーを最新にします（NVIDIA のサイトか NVIDIA App から）。
2. 次のページを開き、右上の「Download raw file」（下向き矢印のボタン）を押して、`install.bat` をダウンロードします。
   https://github.com/Myohga/cellcounter/blob/main/install.bat
   ブラウザーに「一般的にダウンロードされていません」などと出たときは、「…」→「保存」（または「保持する」）を選びます。
3. ダウンロードした `install.bat` をダブルクリックします。「Windows によって PC が保護されました」と出たときは、「詳細情報」→ [実行] を押します。
4. 黒い画面が開き、`[1/6]` から `[6/6]` まで順に進みます。途中で何かを選ぶ必要はありません。
   最後に `Done.` と出たら、何かキーを押して画面を閉じます。`FAILED` と出て止まったときは、「うまくいかないとき」を見てください。
5. 手順 6 に進みます。デスクトップに「cellcounter」のショートカットができているので、`launch.bat` の代わりにそれを使えます。

install.bat が行うこと:

- Miniforge が無ければ、ダウンロードして `%USERPROFILE%\miniforge3` に入れます。
  Windows のユーザー名に日本語や空白が入っているときは、`C:\miniforge3` に入れます。
  Miniforge・Anaconda・Miniconda がすでに入っていれば、それを使います。
- `conda init cmd.exe` を実行し、`cellcounter` 環境（Python 3.12 と git）を作ります。
- cellcounter 本体を `C:\cellcounter` に取ってきます（git clone）。
- NVIDIA の GPU があれば、GPU 版の PyTorch を入れます。CPU 版が入っていれば入れ替えます。
- cellcounter が使う部品を入れ（`pip install -e .`）、デスクトップにショートカットを作ります。

もう一度実行しても大丈夫です。済んでいる手順は飛ばします。
手で入れた PC でも、`C:\cellcounter\install.bat` をダブルクリックすると、足りないものだけを入れます。

### 手で入れる

次の 1〜6 を順に行います。

1. Miniforge（Python と conda）を入れる
2. cellcounter 用の環境を作る
3. cellcounter 本体を取ってくる（git clone）
4. GPU 版の PyTorch を入れる（NVIDIA の GPU がある PC だけ）
5. cellcounter が使う部品を入れる
6. 起動して確かめる

### 1. Miniforge を入れる

Miniforge は、Python と conda（Python の環境をソフトごとに分けて管理する道具）をまとめて入れるソフトです。無償で使えます。

1. 次の URL から、Windows 用のインストーラー（`Miniforge3-Windows-x86_64.exe`）をダウンロードします。
   https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Windows-x86_64.exe
2. ダウンロードしたファイルを開きます。「Windows によって PC が保護されました」と出たときは、「詳細情報」→ [実行] を押します。
3. 選択肢はすべて既定のまま（「Just Me」のまま、PATH への追加もしない）、[Next]・[I Agree]・[Install]・[Finish] と進めます。
   ただし、Windows のユーザー名に日本語や空白が入っているときは、インストール先を選ぶ画面（Choose Install Location）で
   `C:\miniforge3` に変えてください。そのままだと、あとの手順で失敗することがあります。

Anaconda や Miniconda がすでに入っている PC では、それを使っても構いません。
その場合は手順 1 を飛ばし、以下の「Miniforge Prompt」を「Anaconda Prompt」に読み替えてください。

### 2. cellcounter 用の環境を作る

スタートメニューで「Miniforge Prompt」を探して開きます。黒い画面が開き、行頭に `(base)` と出ます。
次のコマンドを 1 行ずつ貼り付けて、Enter を押します。2 行目は数分かかります。

```bat
conda init cmd.exe
conda create -n cellcounter python=3.12 git -y
conda activate cellcounter
```

- 1 行目は、`launch.bat` から conda を使えるようにする設定です。
  あとに「close and re-open your current shell」と出ますが、閉じずにそのまま続けて構いません。
- 2 行目で、Python と git（手順 3 で cellcounter 本体を取ってくる道具）を入れます。
  Python は 3.12 を使ってください。3.11 以前では、.czi を読む部品（czifile）が入りません。
- 3 行目のあと、行頭が `(base)` から `(cellcounter)` に変わります。手順 3〜5 は、この画面のまま続けます。
  画面を閉じてしまったときは、Miniforge Prompt を開き直し、`conda activate cellcounter` を実行してから続けます。

### 3. cellcounter 本体を取ってくる

手順 2 の画面のまま、次を実行します。

```bat
git clone https://github.com/Myohga/cellcounter.git C:\cellcounter
```

`C:\cellcounter` というフォルダができ、中に `launch.bat` などが入ります。

- 以下は `C:\cellcounter` に置いたものとして説明します。別の場所に置くときは、日本語や空白を含まない場所を選び、
  コマンドの `C:\cellcounter` を読み替えてください。
- `C:\cellcounter` の中のファイルは書き換えないでください。あとで更新（`git pull`）できなくなります。

### 4. GPU 版の PyTorch を入れる（NVIDIA の GPU がある PC だけ）

核の検出（Cellpose）は、GPU を使うと速く終わります。GPU が無くても動きますが、1 枚に 10 分以上かかります。
NVIDIA の GPU が無い PC では、この手順を飛ばしてください。

1. NVIDIA のドライバーを最新にします（NVIDIA のサイトか NVIDIA App から）。
2. 手順 2 の画面で `nvidia-smi` と入力し、表の右上の「CUDA Version」が 12.8 以上であることを確かめます。
3. 次のコマンドで、GPU 版の PyTorch を入れます。約 3 GB をダウンロードします。

```bat
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
```

- この手順は、必ず手順 5 より前に行ってください。先に手順 5 を済ませると CPU 版の PyTorch が入り、
  上のコマンドでは入れ替わりません（入れ替え方は「うまくいかないとき」にあります）。
- RTX 50 シリーズ（RTX 5060 など）は、cu128 以降の版でないと動きません。

### 5. cellcounter が使う部品を入れる

手順 2 の画面のまま、次を実行します。

```bat
cd /d C:\cellcounter
pip install -e .
```

napari・Cellpose・PyTorch などをダウンロードするため、10〜30 分ほどかかります。
最後に `Successfully installed` で始まる行が出れば完了です。赤い `ERROR` が出たときは、「うまくいかないとき」を見てください。

このあとは `C:\cellcounter` を動かしたり、名前を変えたりしないでください。動かしたときは、手順 5 をやり直します。

### 6. 起動して確かめる

1. `C:\cellcounter\launch.bat` をダブルクリックします。黒い画面が開き、しばらくすると cellcounter の画面が出ます。
   黒い画面は、cellcounter を使っているあいだ閉じないでください（閉じると cellcounter も終わります）。
2. F1 を押し、ヘルプの下に出る動作環境を確かめます。GPU 版を入れた PC では、「GPU」の欄が「使えます（GPU の名前）」になります。
3. 初めて [判定] を押したときだけ、核の検出に使う Cellpose のモデル（約 1.2 GB）をダウンロードします。
   インターネットにつながった状態で、終わるまで待ってください。進み具合は黒い画面に出ます。
   モデルは `%USERPROFILE%\.cellpose\models` に保存され、2 回目からはダウンロードしません。

`launch.bat` を右クリック →「送る」→「デスクトップ (ショートカットを作成)」で、デスクトップから開けるようにしておくと便利です
（Windows 11 では、右クリックのあと「その他のオプションを確認」を押すと「送る」が出ます）。

### 更新するとき

`C:\cellcounter\update.bat` をダブルクリックします。新しい版を取ってきて（`git pull`）、増えた部品を入れます（`pip install -e .`）。
最後に `Done.` と出たら、何かキーを押して画面を閉じます。

`update.bat` が無い古い版では、1 回だけ、Miniforge Prompt で次を実行して更新します。そのあとは `update.bat` を使えます。

```bat
conda activate cellcounter
cd /d C:\cellcounter
git pull
pip install -e .
```

結果（.czi と同じフォルダの `<ファイル名>_cellcounter`）と設定（`%APPDATA%\cellcounter`）は別の場所にあるので、更新しても消えません。

### うまくいかないとき

install.bat・update.bat が止まったとき:

| 症状 | 対処 |
|---|---|
| `FAILED: could not download and install Miniforge` | インターネットにつながっているか確かめます。大学や会社のネットワークでダウンロードが止められているときは、手順 1 のとおり Miniforge を手で入れてから、install.bat を実行し直します |
| `FAILED: could not create the conda environment`、`could not install the GPU version of PyTorch`、`could not install the Python packages with pip` | 多くは、ダウンロードの途中で通信が切れたためです。install.bat を実行し直してください（済んだ手順は飛ばします）。何度やっても止まるときは、上に出ている赤い `ERROR` を下の表で探します |
| `FAILED: could not use Python 3.12 or later in the environment` | 前に作った環境の Python が古いです。Miniforge Prompt で `conda remove -n cellcounter --all -y` を実行して環境を消してから、install.bat を実行し直します |
| `FAILED: could not get cellcounter with git clone` | `C:\cellcounter` に別のものが入っているか、通信が切れました。`C:\cellcounter` があれば別の名前に変えてから、install.bat を実行し直します |
| install.bat の最後に `WARNING: An NVIDIA GPU was found, but PyTorch cannot use it` と出る | NVIDIA のドライバーが古いです。ドライバーを最新にして PC を再起動し、install.bat を実行し直します |
| update.bat で `FAILED: git pull` と出る | インターネットにつながっているか確かめます。`would be overwritten` と出ているときは、`C:\cellcounter` の中のファイルが書き換えられています。Miniforge Prompt で `cd /d C:\cellcounter` と `git restore .` を実行して元に戻してから（書き換えた内容は消えます）、update.bat を実行し直します |

そのほか:

| 症状 | 対処 |
|---|---|
| `launch.bat` を開くと `Python was not found`、または「'python' は、内部コマンドまたは外部コマンド…として認識されていません」と出る | 手順 2 の `conda init cmd.exe` が済んでいません。Miniforge Prompt で実行してから、`launch.bat` を開き直してください |
| `launch.bat` を開くと `EnvironmentNameNotFound` と出る | 環境ができていません。手順 2 からやり直してください（`C:\cellcounter` がすでにあれば、手順 3 は飛ばします） |
| `git` が「内部コマンドまたは外部コマンド…として認識されていません」と出る | 行頭が `(cellcounter)` になっていません。`conda activate cellcounter` を実行してから、もう一度実行してください。それでも出るときは、`conda install git -y` で git を入れます |
| `git clone` で `already exists and is not an empty directory` と出る | `C:\cellcounter` がすでにあります。前に取ってきたものなら、手順 3 は済んでいるので、手順 4 に進んでください |
| `launch.bat` を開くと `ModuleNotFoundError` と出る | 部品が入っていません。Miniforge Prompt で `conda activate cellcounter` を実行してから、手順 5 をやり直してください |
| `pip install -e .` で `No matching distribution found for czifile` と出る | 環境の Python が 3.12 ではありません。Miniforge Prompt を開き直し、`conda remove -n cellcounter --all -y` で環境を消してから、手順 2 からやり直してください（手順 3 は飛ばします） |
| `pip install` で `Long Path` を含むエラーが出る | エラー文にある https://pip.pypa.io/warnings/enable-long-paths の手順で、長いパスを有効にしてください（管理者の権限が要ります） |
| GPU があるのに、F1 の「GPU」が「使えません」になる | `nvidia-smi` の CUDA Version が 12.8 未満なら、ドライバーを更新します。12.8 以上なら CPU 版の PyTorch が入っているので、`C:\cellcounter\install.bat` を実行し直すか、下のコマンドで入れ替えてください |
| 初めての判定がなかなか終わらない | Cellpose のモデルをダウンロードしています。黒い画面で進み具合を確かめてください |

CPU 版の PyTorch を GPU 版に入れ替える（Miniforge Prompt で）:

```bat
conda activate cellcounter
pip uninstall -y torch torchvision
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
```

## 使い方（画面）

`launch.bat` をダブルクリックするか、Miniforge Prompt で `conda activate cellcounter` を実行したあと、次のコマンドで画面を開きます。

```bat
python -m cellcounter
```

右側のパネルを ① から順に進めます。前の段階が済むまで、次のタブは押せません。

| タブ | すること |
|---|---|
| ① ファイル | .czi を開く（Ctrl+O、ドラッグ＆ドロップ、最近使ったファイル）。シーンが複数あれば選ぶ |
| ② 設定 | チャンネル表でマーカー名・染まる場所・判定の ON/OFF を決める。陰性対照の .czi を足す。[判定]（Ctrl+J）を押す |
| ③ 判定・修正 | 画像の上のタブで組み合わせを切り替え、× をクリックで足す・消す |
| ④ 出力 | [確定]（Ctrl+Enter）で Excel・確認用画像・作業ファイルを書き出す |

- **● の付いたチャンネル**（② の「核を数える」の列）で核を検出して数えます。ふつうは DAPI / Hoechst で、自動で選ばれます。
  選び直しても、ほかの行に入れた名前や設定は消えません。
- **背景に表示する画像**は ③ の上の欄で選びます。チェックを付けたチャンネルを、ZEN で付けた色のまま重ねます。
  選んだ内容は組み合わせのタブごとに覚え、確認用画像にも同じものが出ます。明るさのスライダーは表示だけに効きます。
- **×** は細い線で描きます。「× を表示する」のチェックを外すと、一時的に消せます。
  黄 = 自動で付いた ×、水色 = 人が足した ×、赤 = 人が消した × です。
- クリックの意味は、開いているタブで変わります。
  - 「DAPI のみ」: × のある核 → 数えない ／ × の無い核 → 数える ／ 何も無い場所 → 円い核を作る
  - 「DAPI＋マーカー」: × のある核 → 陰性 ／ × の無い核 → 陽性 ／ 何も無い場所 → 円い核を作って陽性
- 元に戻すは Ctrl+Z、やり直しは Ctrl+Shift+Z か Ctrl+Y です。キーの一覧は F1 で出ます。
- ② の設定を変えたあとは、[判定] を押し直すまで × は前の判定のままです（画面の下に知らせが出ます）。
- 途中でやめるときは「作業を保存」（Ctrl+S）で保存し、あとで「作業ファイルを開く」で続きから始められます。
- エラーの詳細は `%APPDATA%\cellcounter\cellcounter.log` に残ります。

## 使い方（コマンドライン）

コマンドは、Miniforge Prompt で `conda activate cellcounter` を実行してから使います。

シーンとチャンネルを確認する:

```bat
python -m cellcounter info "D:\data\sample.czi"
```

判定して結果を書き出す:

```bat
python -m cellcounter analyze "D:\data\sample.czi" ^
    --marker "AF488=MAP2" --marker "AF555=Islet-1" --marker "AF647=NKX2.1" ^
    --control "D:\data\negative.czi"
```

- `--marker` は `チャンネル=マーカー名` です。チャンネルは番号・名前・色素名のどれでも指定できます。
- 染まる場所（核 / 細胞質 / 膜 / 突起 / 点状）はマーカー名の辞書から推定します。
  辞書に無い名前は `--marker "AF647=MyProtein:核"` のように指定します。指定が無ければ止まります。
- `--control` は陰性対照の .czi です。何度でも指定でき、全シーンの細胞を合計して使います。
- `--control` を省くと固定の閾値で判定し、結果のすべてに「暫定（陰性対照なし）」と表示します。
- そのほかの指定は `python -m cellcounter analyze --help` で確認できます。

結果は .czi と同じフォルダの `<ファイル名>_cellcounter\` に出ます。

| ファイル | 内容 |
|---|---|
| `results.xlsx` | Summary / Coexpression / Cells / Settings の 4 シート。グラフは Excel 上で編集できます |
| `確認_*.png` | 組み合わせごとの確認用画像。自動・人が足した・人が消したを色分けしています |
| `<ファイル名>.cellcounter` | 作業ファイル。あとで続きから開けます |

## そのほかの機能

### Z スタックとタイル画像

- タイル画像は、貼り合わせた 1 枚の画像として読み込みます。
- Z スタックは、① の「Z の重ね方」で 1 枚にします（最大値投影 / 平均投影 / いちばん明るい 1 枚 /
  枚数を指定して 1 枚だけ）。コマンドラインでは `--z max`、`--z plane:3` のように指定します。
- 厚い組織では、最大値投影にすると深さの違う核が重なります。その場合は 1 枚だけを使ってください。

### 一括処理

メニューの「実行 → 一括処理…」で、いま開いている画像と同じチャンネル表・設定・陰性対照を使い、
選んだ .czi（中の全シーン）をまとめて判定します。コマンドラインでは次のとおりです。

```bat
python -m cellcounter batch "D:\data\実験フォルダ" --marker "AF488=MAP2" --control "D:\data\negative.czi" --out "D:\data\結果"
```

- 出力先に、画像ごとのフォルダ（結果一式と作業ファイル）と、まとめの `batch.xlsx` ができます。
- `batch.xlsx` の Images シートは画像ごとの陽性率、Conditions シートは条件ごとの平均 ± SD と棒グラフです。
- 条件の名前は、ファイル名から末尾の通し番号を除いたものです（`ctrl_1.czi` と `ctrl_2.czi` は `ctrl`）。
  画面からの一括処理では、始める前に書き換えられます。
- × の修正は、画像ごとの作業ファイルを開いて行い、同じ場所に保存します。そのあと
  「実行 → 一括処理の集計をやり直す…」（または `python -m cellcounter batch-refresh "D:\data\結果"`）で
  `batch.xlsx` を作り直します。

### 閾値と陽性率の曲線

`results.xlsx` の Thresholds シートに、マーカーごとに「閾値を動かしたときの陽性率」の表とグラフが出ます。
陰性対照があれば、対照の曲線と、実際に使った閾値の位置（縦線）も重ねます。

### 目視判定との比較

③ の「目視判定モード」にチェックを入れると、マーカーのタブで自動判定の × と件数を隠します。
陽性だと思う核をクリックして × を付け、終わったらチェックを外します。
目視を正解としたときの自動判定の感度・特異度・κ が ③ に出て、`results.xlsx` の Agreement シートにも残ります。
目視で付けた × は、確定判定（Summary の陽性数）には影響しません。

### 突起マーカーの面積

染まる場所が「突起」のマーカーは、Summary に「陽性面積／核 (µm²)」が出ます。
画像全体で閾値を超えた画素の面積を、数える核の数で割った値です。

### 自動保存

保存していない × の修正があるあいだ、1 分ごとに控えを書きます。
ソフトが途中で落ちたときは、次に起動したときに「続きから開きますか？」と尋ねます。

### スケールバーと動作環境

画像の右下にスケールバー（µm）が出ます。F1 のヘルプの下に、版と GPU が使えるかどうかが出ます。

## 陽性判定の方法

判定法は `cellcounter/judge.py` だけにあります。

| 染まる場所 | 細胞ごとの値 | 陽性の条件 |
|---|---|---|
| 核 | (核内の平均 + c) ÷ (核のすぐ外側のリングの平均 + c) | 値 > 閾値 |
| 細胞質 | 核とその外側 3 µm で、背景を引いた明るさの 75 パーセンタイル | 同上（＝画素の 25% 超が閾値超え） |
| 膜 | 核の外側 3 µm で、同 75 パーセンタイル | 同上（25% 超） |
| 突起 | 核の外側 2 µm で、同 90 パーセンタイル | 同上（10% 超） |
| 点状 | 核の外側 3 µm で、輝点を強調したあとの 97 パーセンタイル | 同上（3% 超） |

- 閾値は、陰性対照の細胞の値の 99 パーセンタイルです（`--percentile 95` で切り替え）。
- c は全階調の 1% です。背景が 0 に近い画像で比が発散するのを防ぎます。
- リングは核の縁から 0.3 µm 空けた幅 1.5 µm で、ほかの核の近くの画素は除きます。
- 陰性対照が無いときの固定値は、核が比 1.5、ほかは局所背景の 2.0 倍です。
  どちらも実データでの裏付けが無い仮の値です。
- 閾値ちょうどの細胞は陰性です。
- 周りに測る場所が無い核は「判定不能」とし、陰性として数えます。件数は Summary に出ます。

## テスト

Miniforge Prompt で `conda activate cellcounter` と `cd /d C:\cellcounter` を実行してから、次を実行します。

```bat
pip install -e ".[test]"
python -m pytest
```

合成画像だけを使います。実画像も Cellpose も不要です。

## 実データで確かめる手順

判定法の正確さは、次の 2 つで評価してください。

### 1. 陰性対照の陽性率

陰性対照を 2 視野以上撮り、片方を対照、もう片方を実験画像として判定します。

```bat
python -m cellcounter analyze "negative_2.czi" --marker "AF555=Islet-1" --control "negative_1.czi"
```

陽性率が約 1%（`--percentile 95` なら約 5%）なら、閾値の決め方は期待どおりです。
大きく外れるときは、視野ごとの染まりのむらや撮影条件の違いを疑ってください。
撮影条件の違いは警告として表示され、Settings シートにも残ります。

### 2. 目視判定との比較

1. 実験画像を陰性対照つきで判定します。
2. `確認_DAPI＋〇〇.png` を開き、黄色の ×（自動で陽性）を目視の判定と比べます。
3. Cells シートの「〇〇 値」と「〇〇 自動判定」を使い、目視と食い違った細胞の値が
   閾値の近くにあるかを確認します。閾値は Settings シートの「〇〇: 閾値」です。
4. 陽性率がほぼ 0% の視野と、ほぼ 100% の視野の両方で確かめてください
   （旧版の Otsu は、どちらでも半々のほうへ引っ張られました）。

### 階調の警告

読み込み時に、チャンネルごとの明るさの 99 パーセンタイルを調べます。
全階調の 25% 未満、または 90% 超のときは警告が出ます。その画像の陽性率は暫定値です。
