# Brand

## The mark

Four bars of decreasing length, with a bracket closing around all of them.

A ranking, held. The bracket is the whole family: every contract here groups
things that cannot be separated rather than pretending to separate them, so the
mark shows the **refusal** rather than only the order. It is also where the name
came from -- a bracket is both a band you group into and a structure you rank
with, which is exactly what these four do.

### The family

Each contract carries the same geometry with its own answer. There is no second
hue anywhere: these are four rungs of one ladder, not four products, and a
different colour would say they were unrelated. What changes is the shape, and
the chalk stroke in every mark is the thing that contract refuses to do.

| Mark | Geometry | What it says |
|---|---|---|
| [`mark.svg`](mark.svg) | four bars, one bracket around all | the catalogue |
| [`family/tiebreak.svg`](family/tiebreak.svg) | two bars of **equal** length, joined | are these two different at all |
| [`family/slate.svg`](family/slate.svg) | four descending, the tied pair joined | an ordering with the ties left in |
| [`family/cutline.svg`](family/cutline.svg) | four descending, one line across | who is above the line |
| [`family/winnow.svg`](family/winnow.svg) | two piles, one lone chalk mark between | three buckets, the middle one uncertain |

Built on a 100 × 100 grid. Stroke weight 8.5, round caps, corner radius 18. The
tie bracket is lighter, at 3.5, in chalk rather than the accent, so it reads as
annotation rather than as a fifth bar.

- **Clear space:** half the mark height on every side.
- **Smallest size:** 18px alone, 24px locked to the wordmark. Verified — all four
  bars and the bracket stay separable.
- **Never:** a second hue, a gradient, an outline version, a drop shadow, or the
  mark rotated. The geometry carries the meaning.

## Palette

| Token | Hex | Use |
|---|---|---|
| `ink` | `#0C0D10` | the mark's field, any dark surface |
| `chalk` | `#E8E6E1` | the wordmark, primary text, the tie bracket. Never pure white |
| `accent` | `#E0A23C` | the bars, one primary action, one live state |
| `muted` | `#9AA0A8` | secondary text |
| `rule` | `#232830` | hairlines and dividers |

One accent, used sparingly. On the social card it appears exactly three times:
the top bar, the mark, and the footer line.

The accent is distinct from its two siblings on purpose: Crosscheck is violet
`#8B7CF6`, Tolerance is green `#3DD68C`. Same geometry language, different hue,
so the three read as one hand without reading as one product.

## Type

Inter, weights 400 and 700. Tracking tightened to -1.4 on the wordmark and -2.6
at display size. Monospace for anything that is a value rather than a sentence:
`ui-monospace, SFMono-Regular, Menlo, monospace`. The wordmark is always
lowercase.

## Files

| File | What it is |
|---|---|
| `mark.svg` | the Bracket mark alone, 100 × 100 |
| `lockup.svg` | mark plus wordmark |
| `social.svg` | 1280 × 640 source |
| `social.png` | export, for Settings → Social preview |

## Re-exporting the social card

```bash
pip install cairosvg
python -c "import cairosvg; cairosvg.svg2png(url='brand/social.svg', \
    write_to='brand/social.png', output_width=1280, output_height=640)"
```

Upload under **Settings → General → Social preview**. GitHub uses it whenever a
link to the repository is shared, including inside a portal submission.
