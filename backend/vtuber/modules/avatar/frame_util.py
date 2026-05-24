"""渲染帧工具（Core 内部）。"""


def black_rgb(width: int, height: int) -> tuple[bytes, int, int]:
    return (bytes(width * height * 3), width, height)
