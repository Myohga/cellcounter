"""コマンドラインから 1 ファイルを処理する。"""

from __future__ import annotations

import argparse
import os
import sys

from .batch import BATCH_NAME, BatchRow, list_items, refresh_batch, run_batch

from .channels import ChannelRow, ChannelTable, apply_preset, build_table, load_preset
from .control import collect_control
from .czi import list_scenes, read_scene
from .dyes import normalize
from .export import export_results
from .markers import LOCATION_SPECS, location_key
from .pipeline import open_session, run_detection, run_judgement
from .session import Session
from .settings import Z_PROJECTIONS, Settings
from .tally import summarize


def _find_row(table: ChannelTable, text: str) -> ChannelRow:
    """チャンネルを番号・名前・色素名のどれかで指定する。"""
    if text.isdigit():
        return table.row(int(text))
    wanted = normalize(text)
    hits = [row for row in table.rows if wanted in (normalize(row.name), normalize(row.dye))]
    if len(hits) != 1:
        names = "、".join(f"{row.index}:{row.name}" for row in table.rows)
        raise ValueError(f"チャンネル '{text}' を 1 つに決められません（{names}）。")
    return hits[0]


def _set_marker(table: ChannelTable, text: str) -> None:
    """'チャンネル=マーカー名' または 'チャンネル=マーカー名:染まる場所'。"""
    channel, separator, rest = text.partition("=")
    if not separator or not rest:
        raise ValueError(f"--marker は 'AF488=MAP2' や 'AF488=MAP2:突起' の形で指定してください: {text}")
    marker, separator, place = rest.rpartition(":")
    if not separator:
        marker, place = rest, ""
    location = location_key(place) if place else None
    table.set_marker(_find_row(table, channel).index, marker, location)


def _print_table(table: ChannelTable) -> None:
    for row in table.rows:
        if row.role == "dapi":
            role = "DAPI（核・分母）"
        elif row.role == "unused":
            role = "使わない（蛍光ではない）"
        elif row.marker:
            place = LOCATION_SPECS[row.location].label if row.location else "未選択"
            role = f"{row.marker}／{place}／判定 {'ON' if row.judge else 'OFF'}"
        else:
            role = "未設定"
        wave = f"{row.emission_nm:.0f} nm" if row.emission_nm else "波長不明"
        print(f"  {row.index}: {row.name:<14} {row.dye or '色素不明':<8} {wave:>8}  {role}")


def _info(args: argparse.Namespace) -> int:
    for scene in list_scenes(args.czi):
        sizes = " ".join(f"{axis}={size}" for axis, size in scene.sizes.items())
        print(f"シーン {scene.index}: {scene.name}（{sizes}）")
    image = read_scene(args.czi)
    um = f"{image.meta.um_per_px:.4f}" if image.meta.um_per_px else "取得できず"
    print(f"µm/px: {um} / ビット深度: {image.meta.bits} / 対物: {image.meta.objective or '取得できず'}")
    _print_table(build_table(image.meta))
    for warning in image.warnings:
        print(f"警告: {warning}")
    return 0


def _configure(args: argparse.Namespace, path: str, scene: int) -> Session:
    """コマンドラインの指定から、チャンネル表と設定を決めた作業状態を作る（検出はまだ）。"""
    image = read_scene(path, scene, args.z)
    if args.um_per_px:
        image.meta.um_per_px = args.um_per_px
    table = build_table(image.meta)
    if args.preset:
        apply_preset(table, load_preset(args.preset))
    if args.dapi:
        table.set_dapi(_find_row(table, args.dapi).index)
    for text in args.marker:
        _set_marker(table, text)
    problems = table.problems()
    if problems:
        raise ValueError("チャンネル表に直すところがあります:\n" + "\n".join(problems))
    _print_table(table)

    settings = Settings(z_projection=args.z)
    settings.detection.use_gpu = not args.cpu
    settings.detection.nucleus_diameter_um = args.diameter_um
    settings.judge.control_percentile = args.percentile
    return open_session(image, table, settings)


def _control_sources(args: argparse.Namespace) -> list[tuple[str, int]]:
    return [(path, scene.index) for path in args.control for scene in list_scenes(path)]


def _analyze(args: argparse.Namespace) -> int:
    session = _configure(args, args.czi, args.scene)
    print("核を検出しています（Cellpose。CPU では数分かかります）…")
    run_detection(session)
    control = None
    if args.control:
        print("陰性対照を測っています…")
        control = collect_control(session, _control_sources(args))
    run_judgement(session, control)
    folder = export_results(session, args.out)

    for row in summarize(session):
        rate = f"{row.rate:.1f}%" if row.rate is not None else "—"
        print(f"  {row.name}: {row.positive} / {row.total}（{rate}）")
    if session.provisional:
        print("※ 暫定（陰性対照なし）: 固定の閾値で判定しています。")
    for warning in session.warnings:
        print(f"警告: {warning}")
    print(f"出力先: {folder}")
    return 0


def _print_batch(rows: list[BatchRow], folder: str) -> None:
    for row in rows:
        rates = "、".join(f"{marker} {rate:.1f}%" if rate is not None else f"{marker} —"
                          for marker, rate in row.rates.items())
        print(f"  [{row.condition}] {row.file}（シーン {row.scene}）: 核 {row.total} 個 ／ {rates}")
    print(f"まとめ: {os.path.join(folder, BATCH_NAME)}")


def _batch(args: argparse.Namespace) -> int:
    items = list_items(args.inputs)
    if not items:
        raise ValueError("一括処理する .czi がありません。")
    template = _configure(args, items[0].path, items[0].scene)
    rows = run_batch(items, template, _control_sources(args), args.out, progress=print)
    _print_batch(rows, args.out)
    return 0


def _batch_refresh(args: argparse.Namespace) -> int:
    _print_batch(refresh_batch(args.folder), args.folder)
    return 0


def _gui(args: argparse.Namespace) -> int:
    # 画面を使わない info / analyze では、napari と Qt を読み込まない
    from .gui.app import run

    return run(args.file)


def main(argv: list[str] | None = None) -> int:
    # 日本語 Windows のコンソール（cp932）は µ などを表示できず、print が例外で止まる。
    # コンソール無しで起動したとき（pythonw）は stdout が無い
    for stream in (sys.stdout, sys.stderr):
        if stream is not None:
            stream.reconfigure(errors="replace")

    parser = argparse.ArgumentParser(
        prog="cellcounter", description="免疫染色画像のマーカー陽性判定。何も指定しなければ画面を開く")
    parser.set_defaults(run=_gui, file=None)
    commands = parser.add_subparsers(dest="command")

    gui = commands.add_parser("gui", help="画面を開く（既定）")
    gui.add_argument("file", nargs="?", help="起動してすぐ開く .czi か作業ファイル")
    gui.set_defaults(run=_gui)

    info = commands.add_parser("info", help="シーンとチャンネルの一覧を表示する")
    info.add_argument("czi")
    info.set_defaults(run=_info)

    refresh = commands.add_parser("batch-refresh",
                                  help="一括処理のあと、1 枚ずつ修正した結果で集計し直す")
    refresh.add_argument("folder", help="一括処理の出力フォルダ")
    refresh.set_defaults(run=_batch_refresh)

    analyze = commands.add_parser("analyze", help="1 ファイルを判定して結果を書き出す")
    analyze.add_argument("czi")
    analyze.add_argument("--scene", type=int, default=0)
    analyze.add_argument("--out", help="出力フォルダ（省くと .czi の隣の <名前>_cellcounter）")
    analyze.set_defaults(run=_analyze)

    batch = commands.add_parser("batch", help="複数の .czi（全シーン）を同じ設定で判定してまとめる")
    batch.add_argument("inputs", nargs="+", help=".czi、または .czi の入ったフォルダ")
    batch.add_argument("--out", required=True, help="出力フォルダ")
    batch.set_defaults(run=_batch)

    for command in (analyze, batch):
        _add_judging_options(command)

    args = parser.parse_args(argv)
    try:
        return args.run(args)
    except (ValueError, FileNotFoundError, RuntimeError, IndexError, KeyError) as error:
        print(f"エラー: {error}", file=sys.stderr)
        return 1


def _add_judging_options(analyze: argparse.ArgumentParser) -> None:
    """analyze と batch に共通の、チャンネル表と判定の指定。"""
    analyze.add_argument("--z", default="max",
                         help=f"Z の重ね方: {' / '.join(Z_PROJECTIONS)} / plane:3（3 枚目だけ）")
    analyze.add_argument("--dapi", help="DAPI のチャンネル（自動で決まらないとき）")
    analyze.add_argument("--marker", action="append", default=[],
                         help="例: AF488=MAP2 / AF647=NKX2.1:核（何度でも指定できる）")
    analyze.add_argument("--preset", help="チャンネル表のプリセット (.json)")
    analyze.add_argument("--control", action="append", default=[],
                         help="陰性対照の .czi（何度でも指定できる。全シーンを使う）")
    analyze.add_argument("--percentile", type=float, default=99.0, help="陰性対照のパーセンタイル")
    analyze.add_argument("--um-per-px", type=float, help="µm/px（メタデータに無いとき）")
    analyze.add_argument("--diameter-um", type=float, help="核の直径 µm（省くと自動）")
    analyze.add_argument("--cpu", action="store_true", help="GPU を使わない")
