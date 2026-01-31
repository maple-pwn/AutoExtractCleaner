#!/usr/bin/env python3
from PIL import Image, ImageDraw


def create_icon():
    sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    images = []

    for size in sizes:
        img = Image.new("RGBA", size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        w, h = size
        margin = w // 8

        fill_color = (76, 175, 80, 255)
        outline_color = (255, 255, 255, 255)

        draw.rectangle(
            [margin, margin // 2, w - margin, h - margin // 2],
            fill=fill_color,
            outline=outline_color,
            width=max(1, w // 32),
        )

        corner_size = w // 4
        draw.polygon(
            [
                (w - margin, margin // 2),
                (w - margin + corner_size // 2, margin // 2 + corner_size // 2),
                (w - margin, margin // 2 + corner_size),
            ],
            fill=(255, 255, 255, 200),
        )

        box_margin = w // 4
        draw.rectangle(
            [box_margin, h // 3, w - box_margin, h * 2 // 3], fill=(255, 255, 255, 220)
        )

        images.append(img)

    images[0].save(
        "icon.ico",
        format="ICO",
        sizes=[(img.width, img.height) for img in images],
        append_images=images[1:],
    )
    print("icon.ico created successfully!")


if __name__ == "__main__":
    create_icon()
