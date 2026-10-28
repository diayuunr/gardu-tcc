from datetime import datetime, timedelta, timezone

# Yogyakarta = WIB (UTC+7), tanpa DST — offset tetap cukup dan tidak butuh
# database zona waktu (zoneinfo di Windows butuh paket tzdata tambahan).
WIB = timezone(timedelta(hours=7))


def to_wib(moment: datetime) -> datetime:
    """Kalau `moment` naive dianggap sudah WIB (waktu lokal pengguna)."""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=WIB)
    return moment.astimezone(WIB)
