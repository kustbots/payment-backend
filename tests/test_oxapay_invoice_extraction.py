import pytest

from app.core.errors import UpstreamServiceError
from app.services.oxapay_service import extract_invoice_fields


def test_extract_invoice_fields_real_oxapay_shape():
    # OxaPay's actual v1 response: nested under "data", snake_case keys.
    resp = {
        "data": {"track_id": "1234567890", "payment_url": "https://pay.oxapay.com/1234567890"},
        "message": "success",
        "status": 200,
    }
    track_id, pay_url = extract_invoice_fields(resp)
    assert track_id == "1234567890"
    assert pay_url == "https://pay.oxapay.com/1234567890"


def test_extract_invoice_fields_legacy_top_level_shape():
    resp = {"trackId": "555", "payLink": "https://pay.oxapay.com/555"}
    track_id, pay_url = extract_invoice_fields(resp)
    assert track_id == "555"
    assert pay_url == "https://pay.oxapay.com/555"


def test_extract_invoice_fields_missing_track_id_raises():
    with pytest.raises(UpstreamServiceError):
        extract_invoice_fields({"message": "some unexpected shape"})
