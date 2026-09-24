"""Consume native HA uploads on an executor and retain only bounded UTF-8 bytes."""

from homeassistant.components.file_upload import process_uploaded_file

from .const import MAX_PATCH_BYTES
from .managed_source import validate_content
from .models import PatchError, Status


def read_upload(hass, file_id: str) -> bytes:
    try:
        with process_uploaded_file(hass, file_id) as path:
            with path.open("rb") as stream:
                data = stream.read(MAX_PATCH_BYTES + 1)
            validate_content(data)
            return data
    except (OSError, ValueError) as error:
        if isinstance(error, PatchError):
            raise
        raise PatchError("upload_unavailable", Status.SOURCE_ERROR) from None
