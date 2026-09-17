"""CLI: python -m slide_operator prepare <run-dir>"""
import json
import sys
from pathlib import Path

from .ingest import folder as folder_mod, deck as deck_mod
from .prepare import service_map as sm


def _find(run: Path, stems: tuple[str, ...], exts: tuple[str, ...]) -> Path:
    for stem in stems:
        for ext in exts:
            p = run / f"{stem}{ext}"
            if p.exists():
                return p
    raise SystemExit(f"no {stems[0]}{exts[0]} in {run}")


def prepare(run: Path) -> None:
    fpath = _find(run, ("folder",), (".docx", ".pdf"))
    dpath = _find(run, ("deck",), (".pptx",))
    blocks = folder_mod.load(fpath)
    slides = deck_mod.load(dpath)
    m = sm.build(slides, blocks)

    out = run / "service_map.json"
    out.write_text(sm.to_json(m))

    s = m.stats
    print(f"folder : {fpath.name}  ({s['folder_blocks']} blocks)")
    print(f"deck   : {dpath.name}  ({s['slides']} slides)")
    print(f"anchored          : {s['anchored']}/{s['slides']}  ({s['coverage']:.1%})")
    print(f"  high confidence : {s['high_confidence']}")
    print(f"cover slides      : {s['covers']}")
    print(f"unanchored content: {s['unanchored_content']}")
    print(f"unmatched folder  : {s['unslided_elements']} blocks")
    print(f"\nwrote {out}")

    missing = [b.index for b in m.slides if b.is_cover and not b.released_by]
    print("\n--- sanity gate (3) ---")
    if s["coverage"] < 0.75:
        print("FAIL: too little of the deck anchored to the folder; do not operate.")
    elif missing:
        print(f"WARN: cover slides with no release cue: {missing}")
    else:
        print("PASS: every cover slide has a release cue; coverage acceptable.")
    for b in m.slides:
        if b.is_cover:
            print(f"  cover slide {b.index:>3} [{b.title[:32]:<32}] "
                  f"released by: {b.released_by[:52]!r}")


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "prepare":
        raise SystemExit("usage: python -m slide_operator prepare <run-dir>")
    prepare(Path(sys.argv[2]))
