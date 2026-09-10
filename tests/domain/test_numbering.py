from invoice_manager.domain.numbering import NumberingService, format_number, parse_number


def test_format_number():
    assert format_number("INV", 1) == "INV-0001"
    assert format_number("RCT", 12) == "RCT-0012"


def test_parse_number():
    assert parse_number("INV-0001") == ("INV", 1)
    assert parse_number("QTE-0001") == ("QTE", 1)
    assert parse_number("0001") == ("", 1)
    assert parse_number("not-a-number") is None


def test_reserve_advances():
    svc = NumberingService()
    assert svc.reserve("invoice") == "INV-0001"
    assert svc.reserve("quote") == "QTE-0001"
    assert svc.reserve("invoice") == "INV-0002"
    assert svc.peek("invoice") == "INV-0003"


def test_initial_next_values():
    svc = NumberingService(next_invoice=5)
    assert svc.reserve("invoice") == "INV-0005"


def test_set_next():
    svc = NumberingService()
    svc.set_next("receipt", 10)
    assert svc.reserve("receipt") == "RCT-0010"
