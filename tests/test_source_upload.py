"""Native upload consumption cleans up both accepted and rejected files."""

from uuid import uuid4

import pytest
from homeassistant.components.file_upload import FileUploadData

from custom_components.hapatchy.const import MAX_PATCH_BYTES
from custom_components.hapatchy.models import PatchError
from custom_components.hapatchy.source_upload import read_upload


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        (b"diff contents", None),
        (b"", "empty_patch"),
        (b"\xff", "invalid_encoding"),
        (b"x" * (MAX_PATCH_BYTES + 1), "source_too_large"),
    ],
    ids=["accepted", "empty", "encoding", "size"],
)
async def test_native_upload_is_consumed(hass, tmp_path, payload, reason):
    file_id = uuid4().hex
    directory = tmp_path / file_id
    directory.mkdir()
    (directory / "input.patch").write_bytes(payload)
    data = FileUploadData(tmp_path, {file_id: "input.patch"})
    hass.data["file_upload"] = data
    if reason:
        with pytest.raises(PatchError, match=reason):
            await hass.async_add_executor_job(read_upload, hass, file_id)
    else:
        assert await hass.async_add_executor_job(read_upload, hass, file_id) == payload
    assert not directory.exists()
    assert not data.files


async def test_upload_unavailable(hass):
    with pytest.raises(PatchError, match="upload_unavailable"):
        await hass.async_add_executor_job(read_upload, hass, uuid4().hex)
