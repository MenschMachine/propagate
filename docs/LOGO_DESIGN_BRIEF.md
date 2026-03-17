# Propagate Logo Design Brief — Dandelion Seeds Concept

## Concept
A stylized dandelion with seeds detaching and drifting outward, representing tasks propagating across repositories. The seeds aren't random — they follow directed paths, subtly evoking a DAG structure.

## Visual Elements

### The Stem & Head
- A single thin vertical stem with a minimal circular seed head at the top
- Represents the root execution / entry point
- Should feel geometric, not botanical — clean lines, not wispy

### The Seeds (3-5)
- Each seed is a small node (dot or circle) with a single fine line trailing back toward the head
- Seeds fan outward and downward in an asymmetric but balanced arrangement
- They move in distinct directions — not a uniform burst, but intentional paths (like DAG edges)
- Varying distances from the head suggest different stages of propagation

### Negative Space
- The space between seed paths should feel open and breathable
- Avoid clutter — this needs to read at 16x16px (favicon) and 512x512px equally

## Style

| Attribute | Direction |
|---|---|
| Aesthetic | Geometric minimalism, not illustration |
| Lines | Uniform thin weight, or at most two weights (stem thicker, seed trails thinner) |
| Shapes | Circles for nodes/seeds, straight or gently curved lines for paths |
| Detail level | Abstracted — a developer should see "dandelion" but also "graph" |
| Symmetry | Slightly asymmetric — organic enough to feel alive, structured enough to feel engineered |

## Color

### Primary (monochrome)
- Must work as single-color on white and on dark backgrounds
- Pure black `#000` / pure white `#FFF` versions required

### Accent (optional brand color)
- A muted teal or green (`#2D9F8F` range) — evokes growth, propagation, nature-meets-tech
- Could be used to highlight the seeds while the stem stays neutral
- Alternatively, a warm amber (`#E8A838`) for the seeds to suggest "signal firing"

## Usage Contexts

| Context | Requirements |
|---|---|
| CLI banner | ASCII-art compatible silhouette |
| GitHub avatar | Recognizable at 40x40px |
| Favicon | Reads as a distinct shape at 16x16px — the seed head + 2-3 seeds is enough |
| README header | Full logo with wordmark "propagate" in lowercase monospace to the right |
| Dark terminal | White-on-transparent version |

## Wordmark Pairing
- "propagate" in lowercase
- Monospace font (JetBrains Mono, IBM Plex Mono, or similar)
- Positioned to the right of the icon, vertically centered
- Letter-spacing slightly increased for breathing room

## What to Avoid
- Realistic botanical illustration — this is a dev tool, not a gardening app
- Too many seeds — 3-5 max, or it becomes noise
- Perfectly symmetrical radial burst — that reads as "explosion" or "loading spinner"
- Rounded/bubbly shapes — keep it sharp and precise
- Gradients in the primary mark — flat only

## Reference Mood
Think: the precision of the Git logo meets the organic metaphor of a dandelion. Technical DNA, natural metaphor.
