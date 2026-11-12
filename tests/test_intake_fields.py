import pytest

from ibtoolkit.intake.fields import FIELDS, FLAG, SourcedValue, by_field


def make(**kw):
    base = dict(field="revenue", value=1_000.0, unit="USD", period_type="FY", period_end="2025-12-31",
                source_kind="xbrl", source_ref="10-K FY2025 tag Revenues")
    base.update(kw)
    return SourcedValue(**base)


def test_valid_value():
    v = make()
    assert v.status == "ok" and v.to_dict()["field"] == "revenue"


def test_unknown_field_rejected():
    with pytest.raises(ValueError):
        make(field="ebitda_guess")


def test_wrong_unit_rejected():
    with pytest.raises(ValueError):
        make(unit="shares")


def test_source_required():
    with pytest.raises(ValueError):
        make(source_ref="")


def test_flag_and_index():
    a = make().flag("sign looks odd")
    b = make(field="cash", period_type="instant")
    c = make(segment="Americas")
    assert a.status == FLAG and a.notes == ["sign looks odd"]
    idx = by_field([a, b, c])
    assert set(idx) == {"revenue", "cash"} and by_field([c], "Americas")["revenue"] is c


def test_every_field_has_unit_kind_and_description():
    for name, (unit, kind, desc) in FIELDS.items():
        assert unit and kind in ("flow", "stock") and desc, name
