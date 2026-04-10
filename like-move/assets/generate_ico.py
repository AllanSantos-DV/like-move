"""Generate like-move.ico with multiple resolutions.

Run once to create the icon file used by PyInstaller for the .exe.
Requires: Pillow
"""

from PIL import Image, ImageDraw


def create_cursor_icon(size: int, bg_color: str = "#2ecc71", fg_color: str = "#ffffff") -> Image.Image:
    """Generate a cursor arrow icon at the given size."""
    image = Image.new("RGBA", (size, size), bg_color)
    draw = ImageDraw.Draw(image)

    # Scale factor relative to 64px base
    s = size / 64.0

    # Cursor/arrow polygon (same shape as tray.py)
    arrow_points = [
        (16 * s, 12 * s),
        (16 * s, 52 * s),
        (28 * s, 40 * s),
        (36 * s, 52 * s),
        (42 * s, 46 * s),
        (34 * s, 34 * s),
        (48 * s, 30 * s),
    ]
    draw.polygon(arrow_points, fill=fg_color)

    return image


def main() -> None:
    sizes = [16, 32, 48, 256]

    # Create the largest image and let Pillow generate smaller sizes
    img = create_cursor_icon(256)
    output = "like-move.ico"
    img.save(output, format="ICO", sizes=[(s, s) for s in sizes])
    print(f"Created {output} with resolutions: {sizes}")


if __name__ == "__main__":
    main()
