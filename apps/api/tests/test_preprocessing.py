import io

from PIL import Image

from app.services.image_preprocessing import preprocess_image


def _jpeg_bytes(*, width: int = 20, height: int = 10) -> bytes:
    image = Image.new("RGB", (width, height), color=(120, 80, 40))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG")
    return buffer.getvalue()


def test_preprocessor_normalizes_orientation_and_reencodes_as_jpeg() -> None:
    output = preprocess_image(_jpeg_bytes(width=20, height=10))

    assert output.width == 20
    assert output.height == 10
    assert output.format == "JPEG"
    assert output.content.startswith(b"\xff\xd8\xff")
