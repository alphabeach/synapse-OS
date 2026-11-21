"""PHP landed cost: each term is charged once, in the right order."""
from app.landed import effective_lead_days, landed_cost


def test_php_quote_has_no_fx_and_vat_on_goods_plus_freight():
    # goods 2000 + freight 150 = 2150; no duty; VAT 258
    assert landed_cost(1000, "PHP", 1, 2, 100, 50, 0) == 2150 + round(2150 * 0.12, 2)


def test_usd_quote_converts_and_duty_is_in_the_vat_base():
    # goods 500 + freight 100 = 600; duty 30; VAT 75.60
    assert landed_cost(10, "USD", 50, 1, 60, 40, 0.05) == 705.6


def test_moq_multiplies_goods_not_freight():
    one = landed_cost(10, "USD", 50, 1, 100, 0, 0)
    two = landed_cost(10, "USD", 50, 2, 100, 0, 0)
    assert round(two - one, 2) == round(500 * 1.12, 2)


def test_bench_lead_includes_the_boc_buffer():
    assert effective_lead_days(18, 7) == 25
    assert effective_lead_days(5, 0) == 5
