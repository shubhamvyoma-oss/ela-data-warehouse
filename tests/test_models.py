from __future__ import annotations

from api_scripts.common.models import RawRecord, payload_sha256, stable_record_key


def test_payload_hash_is_independent_of_mapping_order() -> None:
    assert payload_sha256({"a": 1, "b": 2}) == payload_sha256({"b": 2, "a": 1})


def test_stable_record_key_uses_length_prefixes() -> None:
    assert stable_record_key("ab", "c", payload={}) != stable_record_key("a", "bc", payload={})


def test_record_falls_back_to_payload_hash() -> None:
    payload = {"row": 1}
    key = stable_record_key(None, "", payload=payload)
    record = RawRecord(resource="test", record_key=key, payload=payload)

    assert key == f"sha256:{record.checksum}"
