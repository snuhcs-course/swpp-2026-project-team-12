from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image


def image_upload(name="photo.png", size=(64, 48), color=(40, 120, 200)):
    output = BytesIO()
    Image.new("RGB", size, color).save(output, format="PNG")
    return SimpleUploadedFile(name, output.getvalue(), content_type="image/png")


def corrupt_upload(name="broken.png"):
    return SimpleUploadedFile(name, b"not-an-image", content_type="image/png")
