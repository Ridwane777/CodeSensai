#!/usr/bin/env python3
"""
Prepares the AI portrait for the UI: clean cutout, placed on a square canvas.

Input (provided by the team): the portrait as a high-resolution PNG with an alpha channel.
Output: `portrait.webp` in OUT_DIR (WebP with transparency), silhouette anchored bottom-center.

Dependencies (not in the engine requirements): pillow, numpy, scipy.

    python3 prepare_ai_frames.py PORTRAIT.png ../public/ai [--keep-text]

By default, the visor text ("TURNOVER MARKETING", a third-party brand name) is erased.
`--keep-text` keeps it as is.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage as ndi

CANVAS = 1280
FIGURE_FILL = 0.93  # share of the canvas height taken by the silhouette


def smoothstep(x: np.ndarray, lo: float, hi: float) -> np.ndarray:
    t = np.clip((x - lo) / (hi - lo), 0, 1)
    return t * t * (3 - 2 * t)


def clean_matte(rgba: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Removes the milky halo and decontaminates the edges: returns (rgb 0..255, alpha 0..1)."""
    rgb = rgba[..., :3].astype(np.float32)
    alpha = smoothstep(rgba[..., 3].astype(np.float32) / 255.0, 0.35, 0.8)
    solid = alpha >= 0.95
    # outside the opaque core, reuse the color of the nearest opaque pixel
    _, (iy, ix) = ndi.distance_transform_edt(~solid, return_indices=True)
    return np.where(solid[..., None], rgb, rgb[iy, ix]), alpha


def remove_visor_text(rgb: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    """Erases the brown text on the orange visor by replacing it with the surrounding orange."""
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    orange = (r > 215) & (g > 95) & (b < 120) & (alpha > 0.9)
    if orange.sum() < 50:
        return rgb
    closed = ndi.binary_fill_holes(ndi.binary_closing(orange, structure=np.ones((3, 3)), iterations=9))
    text = closed & ~orange & (r > b) & (g < r * 0.75) & (b < 90) & (alpha > 0.5)
    text = ndi.binary_dilation(text, iterations=2) & closed
    if not text.any():
        return rgb
    _, (iy, ix) = ndi.distance_transform_edt(~(orange & ~text), return_indices=True)
    out = rgb.copy()
    out[text] = rgb[iy, ix][text]
    # light smoothing on the retouched area only, to avoid streaks
    blurred = np.stack([ndi.gaussian_filter(out[..., c], 1.6) for c in range(3)], axis=-1)
    soft = ndi.gaussian_filter(text.astype(np.float32), 1.2)[..., None]
    return out * (1 - soft) + blurred * soft


def place(rgb: np.ndarray, alpha: np.ndarray) -> Image.Image:
    """Crops the silhouette, scales it and anchors it bottom-center on a square canvas."""
    mask = alpha > 0.5
    ys, xs = np.where(mask)
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    low = mask[max(y0, y1 - max(2, (y1 - y0) // 12)) : y1]  # the bust centers the image on its bottom 8 %
    cx = np.where(low.any(axis=0))[0].mean()
    pad = 6
    top, left = max(y0 - pad, 0), max(x0 - pad, 0)
    crop = np.dstack([rgb, alpha * 255.0])[top : y1 + pad, left : x1 + pad]
    scale = (CANVAS * FIGURE_FILL) / (y1 - y0)
    im = Image.fromarray(np.clip(crop, 0, 255).astype(np.uint8), "RGBA")
    # RGB and alpha are resized separately so the transparent background color does not bleed
    rgb_img = im.convert("RGB").resize((round(im.width * scale), round(im.height * scale)), Image.LANCZOS)
    a_img = im.getchannel("A").resize(rgb_img.size, Image.LANCZOS)
    out = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    ox = round(CANVAS / 2 - (cx - left) * scale)
    oy = round(CANVAS * 0.975 - (y1 - top) * scale)
    out.alpha_composite(Image.merge("RGBA", (*rgb_img.split(), a_img)), (max(ox, 0), max(oy, 0)))
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("portrait", type=Path)
    p.add_argument("out", type=Path)
    p.add_argument("--keep-text", action="store_true", help="keep the original visor text")
    args = p.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    rgb, alpha = clean_matte(np.array(Image.open(args.portrait).convert("RGBA")))
    if not args.keep_text:
        rgb = remove_visor_text(rgb, alpha)
    place(rgb, alpha).save(args.out / "portrait.webp", quality=88, method=6)
    print(f"portrait.webp written to {args.out}")


if __name__ == "__main__":
    main()
