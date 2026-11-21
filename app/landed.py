"""Philippine landed cost, in one place, so the API and the UI never disagree.

Formula (BOC practice, simplified):
  goods   = unit_price * fx_rate * quantity      (fx = 1 for PHP quotes)
  freight = shipping_php + cold_chain_php
  duties  = (goods + freight) * duty_rate
  VAT     = (goods + freight + duties) * 0.12    (VAT is charged on CIF + duties)
"""

VAT_RATE = 0.12


def landed_cost(unit_price, currency, fx_rate, quantity, shipping_php,
                cold_chain_php, duty_rate):
    rate = fx_rate if currency == "USD" else 1.0
    goods = unit_price * rate * quantity
    freight = shipping_php + cold_chain_php
    duties = (goods + freight) * duty_rate
    vat = (goods + freight + duties) * VAT_RATE
    return round(goods + freight + duties + vat, 2)


def effective_lead_days(lead_time_days, boc_buffer_days):
    return int(lead_time_days) + int(boc_buffer_days)
