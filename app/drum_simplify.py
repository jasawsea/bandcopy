"""ドラムグリッドの簡略化コマンド（純関数・グリッド→新グリッド）。

ドラマーが叩けない難所を軽くする編集ヘルパー。元のグリッドは破壊せず、
変更後の新しいグリッドを返す。KK/SN/HH のうち対象レーンだけを変える。
"""


def _copy_with_lane(grid: dict, lane: str, new_values: list) -> dict:
    """指定レーンだけ差し替えた新しいグリッドを返す（他は元のまま）。"""
    lanes = {k: list(v) for k, v in grid["lanes"].items()}
    lanes[lane] = new_values
    out = dict(grid)
    out["lanes"] = lanes
    return out


def thin_kicks(grid: dict) -> dict:
    """キック間引き：連続した打点の塊を、塊の先頭1発だけにまとめる。

    例 [1,1,1] → [1,0,0]。16分連打・ダブルキックを単発化する。
    単発（隣に打点が無い）キックはそのまま残す。
    """
    kk = grid["lanes"]["KK"]
    # 直前ステップが打点なら（＝塊の途中なら）落とす。判定は元配列で行う。
    new = [1 if (kk[i] and not (i > 0 and kk[i - 1])) else 0 for i in range(len(kk))]
    return _copy_with_lane(grid, "KK", new)


def thin_hihat(grid: dict) -> dict:
    """ハイハットを軽く：今の細かさを見て1段階だけ粗くする。

    16分（裏拍に打点あり）→8分 ／ 8分→4分 ／ 4分以下→変化なし。
    押すたびに一段軽くなる。既存の打点のうち残す位置だけを残す。
    """
    hh = grid["lanes"]["HH"]
    spb = grid["steps_per_bar"]

    def pos(i):
        return i % spb

    has_16th = any(hh[i] and pos(i) % 2 == 1 for i in range(len(hh)))
    has_8th = any(hh[i] and pos(i) % 2 == 0 and pos(i) % 4 != 0 for i in range(len(hh)))

    if has_16th:
        keep = lambda i: pos(i) % 2 == 0   # 8分（表拍）だけ残す
    elif has_8th:
        keep = lambda i: pos(i) % 4 == 0   # 4分だけ残す
    else:
        return _copy_with_lane(grid, "HH", list(hh))  # 既に4分以下：変化なし

    new = [1 if (hh[i] and keep(i)) else 0 for i in range(len(hh))]
    return _copy_with_lane(grid, "HH", new)
