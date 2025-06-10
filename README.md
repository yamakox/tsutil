# tsutil

[TrainScanner](https://github.com/vitroid/TrainScanner)用の動画データを事前処理するためのツール。

[改造版TrainScanner](https://github.com/yamakox/TrainScanner/tree/image-catalog-file)を使って、[連続した画像のカタログファイル](https://yamakox.github.io/trainscanner#連続した画像データの読み込みについて)を読み込める必要があります。

- [tsutil](#tsutil)
  - [特徴](#特徴)
  - [インストール](#インストール)
  - [起動](#起動)

## 特徴

- 動画のトリミング: カメラで撮影した動画の不要な前後部分を無劣化で削除します。
- 動画から連続画像の展開: カメラで撮影した動画の各フレームを連続した画像ファイルに展開します。展開時に輝度や色の調整を行うことができます。
- 画像のブレ・傾き・歪みの補正: 手持ち撮影した動画から展開した連続画像ファイルのブレ、水平出し、台形補正を行います。

## インストール

```bash
mkdir -p <作業ディレクトリ>
cd <作業ディレクトリ>
python3 -m venv venv
source venv/bin/activate
pip3 install git+https://github.com/yamakox/tsutil.git
```

## 起動

```bash
tsutil
```
