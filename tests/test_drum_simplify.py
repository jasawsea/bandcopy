from app.grid import make_template_grid
from app.drum_simplify import thin_kicks, thin_hihat


def _grid(kk=None, sn=None, hh=None, spb=16, bars=1):
    n = bars * spb
    return {
        "tempo": 100.0, "bars": bars, "steps_per_bar": spb,
        "lanes": {
            "KK": kk or [0] * n,
            "SN": sn or [0] * n,
            "HH": hh or [0] * n,
        },
    }


# --- キック間引き（連続した塊を先頭1発にまとめる）---

def test_thin_kicks_collapses_consecutive_run_to_first():
    g = _grid(kk=[1, 1, 1, 0] + [0] * 12)
    out = thin_kicks(g)
    assert out["lanes"]["KK"][:4] == [1, 0, 0, 0]


def test_thin_kicks_keeps_isolated_hits():
    # 単発（隣接なし）はそのまま
    g = _grid(kk=[1, 0, 0, 0, 1, 0, 0, 0] + [0] * 8)
    out = thin_kicks(g)
    assert out["lanes"]["KK"][0] == 1 and out["lanes"]["KK"][4] == 1


def test_thin_kicks_handles_multiple_runs():
    g = _grid(kk=[1, 1, 0, 0, 1, 1, 1, 0] + [0] * 8)
    out = thin_kicks(g)
    assert out["lanes"]["KK"][:8] == [1, 0, 0, 0, 1, 0, 0, 0]


def test_thin_kicks_leaves_other_lanes_untouched():
    g = _grid(kk=[1, 1] + [0] * 14, sn=[0, 0, 0, 0, 1] + [0] * 11,
              hh=[1, 0, 1, 0] * 4)
    out = thin_kicks(g)
    assert out["lanes"]["SN"] == g["lanes"]["SN"]
    assert out["lanes"]["HH"] == g["lanes"]["HH"]


def test_thin_kicks_does_not_mutate_input():
    kk = [1, 1, 1, 0] + [0] * 12
    g = _grid(kk=list(kk))
    thin_kicks(g)
    assert g["lanes"]["KK"] == kk


# --- ハイハットを軽く（1段階ずつ粗く：16分→8分→4分）---

def test_thin_hihat_16th_to_8th():
    g = _grid(hh=[1] * 16)  # 16分すべて
    out = thin_hihat(g)
    # 偶数ステップだけ残る（8分）
    assert out["lanes"]["HH"] == [1 if s % 2 == 0 else 0 for s in range(16)]


def test_thin_hihat_8th_to_quarter():
    g = _grid(hh=[1 if s % 2 == 0 else 0 for s in range(16)])  # 8分
    out = thin_hihat(g)
    # 4分（0,4,8,12）だけ
    assert out["lanes"]["HH"] == [1 if s % 4 == 0 else 0 for s in range(16)]


def test_thin_hihat_quarter_unchanged():
    q = [1 if s % 4 == 0 else 0 for s in range(16)]
    g = _grid(hh=list(q))
    out = thin_hihat(g)
    assert out["lanes"]["HH"] == q


def test_thin_hihat_leaves_other_lanes_untouched():
    g = _grid(kk=[1, 0, 1] + [0] * 13, hh=[1] * 16)
    out = thin_hihat(g)
    assert out["lanes"]["KK"] == g["lanes"]["KK"]


def test_thin_hihat_does_not_mutate_input():
    hh = [1] * 16
    g = _grid(hh=list(hh))
    thin_hihat(g)
    assert g["lanes"]["HH"] == hh


def test_max_notes_overrides_the_profile():
    """max_notes を渡すと難易度の和音上限より優先されること。"""
    import pretty_midi
    from simplify import simplify_midi
    pm = pretty_midi.PrettyMIDI(initial_tempo=120.0)
    inst = pretty_midi.Instrument(program=33)
    # 同時刻に 基音 + オクターブ + オクターブ5度（採譜モデルが出す倍音の形）
    for p in (33, 45, 52):
        inst.notes.append(pretty_midi.Note(velocity=90, pitch=p, start=0.0, end=0.5))
    pm.instruments.append(inst)

    simplify_midi(pm, 3, 120.0, keep="low", verbose=False, max_notes=1)
    pitches = [n.pitch for i in pm.instruments for n in i.notes]
    assert pitches == [33]          # 最低音（基音）だけ残る
