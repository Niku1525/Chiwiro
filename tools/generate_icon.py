import os
import struct

from PIL import Image

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(BASE, "assets", "cinnamoroll-100.ico")
OUTPUT = os.path.join(BASE, "assets", "chiwiro.ico")

SIZES = [16, 20, 24, 32, 40, 48, 64, 96, 128, 256]


def _dib_bytes(image: Image.Image) -> bytes:
    side = image.size[0]
    pixels = bytearray()
    for y in range(side - 1, -1, -1):
        for x in range(side):
            r, g, b, a = image.getpixel((x, y))
            pixels += bytes((b, g, r, a))

    header = struct.pack(
        "<IiiHHIIiiII",
        40,
        side,
        side * 2,
        1, 32, 0,
        len(pixels),
        0, 0, 0, 0,
    )
    mask_row = ((side + 31) // 32) * 4
    return header + bytes(pixels) + b"\x00" * (mask_row * side)


def _crop(image: Image.Image, margin=0.0) -> Image.Image:
    box = image.getbbox()
    if not box:
        return image
    cropped = image.crop(box)

    side = int(max(cropped.size) * (1 + margin * 2))
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.alpha_composite(cropped, ((side - cropped.size[0]) // 2,
                                     (side - cropped.size[1]) // 2))
    return canvas


def main():
    original = Image.open(SOURCE).convert("RGBA")
    print(f"Origen: {os.path.basename(SOURCE)} {original.size[0]}x{original.size[1]}")
    original = _crop(original)
    print(f"Recortado a: {original.size[0]}x{original.size[1]} (sin margen transparente)")

    images = []
    for side in SIZES:
        layer = original.resize((side, side), Image.LANCZOS)
        images.append((side, _dib_bytes(layer)))

    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries = b""
    body = b""
    for side, data in images:
        entries += struct.pack(
            "<BBBBHHII",
            0 if side >= 256 else side,
            0 if side >= 256 else side,
            0, 0, 1, 32,
            len(data),
            offset,
        )
        body += data
        offset += len(data)

    with open(OUTPUT, "wb") as f:
        f.write(header + entries + body)

    print(f"Tamaños: {', '.join(str(t) for t in SIZES)}")
    print(f"Listo: {OUTPUT} ({os.path.getsize(OUTPUT) / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
