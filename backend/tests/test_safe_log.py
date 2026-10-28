import httpx
from google.api_core.exceptions import ResourceExhausted
from supabase import PostgrestAPIError

from app.core.safe_log import safe_error_summary

_SECRET = "RAHASIA-LAPORAN nomor hp 081234567890"


def _summary_of(exc: Exception) -> str:
    """Raise beneran supaya exc punya traceback (dipakai untuk 'lokasi kode')."""
    try:
        raise exc
    except Exception as caught:  # noqa: BLE001
        return safe_error_summary(caught)


def test_postgrest_error_with_pgrst_code_keeps_message_but_drops_details():
    summary = _summary_of(
        PostgrestAPIError(
            {
                "message": "JWT issued at future",
                "code": "PGRST303",
                "hint": None,
                "details": f"Failing row contains ({_SECRET})",
            }
        )
    )

    assert "PGRST303" in summary
    assert "JWT issued at future" in summary
    assert _SECRET not in summary


def test_postgrest_error_with_sqlstate_code_only_keeps_code():
    """Error data Postgres (SQLSTATE) pesan/details-nya bisa memuat nilai baris."""
    summary = _summary_of(
        PostgrestAPIError(
            {
                "message": f'invalid input syntax for type uuid: "{_SECRET}"',
                "code": "22P02",
                "hint": None,
                "details": f"Failing row contains ({_SECRET})",
            }
        )
    )

    assert "code=22P02" in summary
    assert "RAHASIA-LAPORAN" not in summary
    assert "081234567890" not in summary


def test_httpx_status_error_only_keeps_status_code_not_url_or_token():
    """Pesan bawaan httpx.HTTPStatusError memuat URL LENGKAP termasuk query
    string (mis. ?access_token=...) — tidak boleh masuk log."""
    request = httpx.Request("GET", "https://api.mapbox.com/x.json?access_token=SECRET-TOKEN-MAPBOX")
    response = httpx.Response(401, request=request)
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        assert "SECRET-TOKEN-MAPBOX" in str(exc)  # bukti: pesan mentahnya memang bocor
        summary = _summary_of(exc)

    assert "http=401" in summary
    assert "SECRET-TOKEN-MAPBOX" not in summary
    assert "access_token" not in summary


def test_httpx_transport_error_keeps_short_connection_message():
    summary = _summary_of(httpx.RemoteProtocolError("Server disconnected"))

    assert "RemoteProtocolError" in summary
    assert "Server disconnected" in summary


def test_google_api_error_only_keeps_http_code():
    summary = _summary_of(ResourceExhausted(f"429 quota habis untuk input: {_SECRET}"))

    assert "http=429" in summary
    assert "RAHASIA-LAPORAN" not in summary


def test_unknown_error_keeps_type_and_code_location_but_not_message():
    summary = _summary_of(RuntimeError(f"gagal memproses {_SECRET}"))

    assert summary.startswith("RuntimeError")
    assert "RAHASIA-LAPORAN" not in summary
    # Tetap bisa dilacak: nama file & fungsi tempat error dilempar.
    assert "test_safe_log.py" in summary
    assert "_summary_of" in summary
