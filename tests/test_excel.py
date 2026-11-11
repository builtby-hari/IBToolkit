import pytest

from ibtoolkit.excel import USD, Book


def test_input_blue_calc_black_and_names():
    b = Book()
    ws = b.sheet("S", "T")
    b.inp(ws, "B3", 5, USD, name="X_In")
    b.calc(ws, "B4", "=X_In*2", USD, name="X_Out")
    assert ws["B3"].font.color.rgb.endswith("0000FF")
    assert ws["B4"].font.color.rgb.endswith("000000")
    assert set(b.wb.defined_names) == {"X_In", "X_Out"}
    assert b.wb.defined_names["X_Out"].attr_text == "S!$B$4"


def test_calc_rejects_pasted_values():
    b = Book()
    ws = b.sheet("S", "T")
    with pytest.raises(ValueError):
        b.calc(ws, "B4", 10, USD)
