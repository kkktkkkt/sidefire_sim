"""
Test suite for sidefire_simulator.html.

Drives the real file (via a file:// URL) in headless Chromium through Playwright,
calling the app's own top-level functions and DOM directly -- no reimplementation
of app logic except calc_after_tax_income's independent cross-check (see below).

Run: python tests/test_sidefire_simulator.py
Requires network access (Chart.js loads from a CDN at page-load time).
"""
import math
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

HTML_PATH = Path(__file__).resolve().parent.parent / "sidefire_simulator.html"
HTML_URL = HTML_PATH.as_uri()

CHILD_PUBLIC_10 = (
    "{id:1, age:10, elementary:'public', middle:'public', high:'public', univ:'national',"
    " customEnabled:false, custom:{elementary:35, middle:54, high:51, univ:61}}"
)


def js_round(x):
    """Matches JS Math.round semantics (round-half-up), unlike Python's banker's-rounding round()."""
    return math.floor(x + 0.5) if x >= 0 else -math.floor(-x + 0.5)


def reference_after_tax_income(gross_man):
    """Independent Python port of calcAfterTaxIncome(), used only to cross-check the JS formula."""
    gross = gross_man * 10000
    if gross <= 1_625_000:
        deduction = 550_000
    elif gross <= 1_800_000:
        deduction = gross * 0.4 - 100_000
    elif gross <= 3_600_000:
        deduction = gross * 0.3 + 80_000
    elif gross <= 6_600_000:
        deduction = gross * 0.2 + 440_000
    elif gross <= 8_500_000:
        deduction = gross * 0.1 + 1_100_000
    else:
        deduction = 1_950_000

    social_insurance = gross * 0.145
    basic_deduction = 480_000 if gross <= 24_000_000 else 0
    resident_basic_deduction = 430_000 if gross <= 24_000_000 else 0
    taxable = max(0, gross - deduction - social_insurance - basic_deduction)

    if taxable <= 1_950_000:
        income_tax = taxable * 0.05
    elif taxable <= 3_300_000:
        income_tax = taxable * 0.10 - 97_500
    elif taxable <= 6_950_000:
        income_tax = taxable * 0.20 - 427_500
    elif taxable <= 9_000_000:
        income_tax = taxable * 0.23 - 636_000
    elif taxable <= 18_000_000:
        income_tax = taxable * 0.33 - 1_536_000
    elif taxable <= 40_000_000:
        income_tax = taxable * 0.40 - 2_796_000
    else:
        income_tax = taxable * 0.45 - 4_796_000
    income_tax *= 1.021

    municipal_tax = max(0, gross - deduction - social_insurance - resident_basic_deduction) * 0.10

    net_yen = gross - income_tax - municipal_tax - social_insurance
    return js_round(net_yen / 10000)


def parse_man_yen(text):
    """Parses formatMan() output ("3,000 万円" or "1.5億円") back to a plain number."""
    text = text.strip()
    if text.endswith("億円"):
        return float(text.replace("億円", "")) * 10000
    return float(text.replace(" 万円", "").replace(",", ""))


# ----------------------------------------------------------------------------
# Test bodies. Each receives a fresh `page` already loaded with the simulator.
# ----------------------------------------------------------------------------

def test_format_man(page):
    vals = page.evaluate(
        """() => ({
            zero: formatMan(0),
            small: formatMan(9999),
            oku: formatMan(10000),
            okuFrac: formatMan(12000),
            neg: formatMan(-500),
            undef: formatMan(undefined),
            nan: formatMan(NaN)
        })"""
    )
    assert vals["zero"] == "0 万円", vals
    assert vals["small"] == "9,999 万円", vals
    assert vals["oku"] == "1億円", vals
    assert vals["okuFrac"] == "1.2億円", vals
    assert vals["neg"] == "-500 万円", vals
    assert vals["undef"] == "― 万円", vals
    assert vals["nan"] == "― 万円", vals


def test_calc_after_tax_income(page):
    for gross_man in [0, 100, 162.5, 180, 360, 660, 700, 850, 900, 1200, 2400, 3000]:
        actual = page.evaluate(f"calcAfterTaxIncome({gross_man})")
        expected = reference_after_tax_income(gross_man)
        assert actual == expected, f"gross={gross_man}万: expected {expected}, got {actual}"

    # cross-check against the live UI display for the app's own default income (700万)
    page.fill("#annualIncome", "700")
    display = page.inner_text("#afterTaxDisplay")
    expected700 = reference_after_tax_income(700)
    assert str(expected700) in display.replace(",", ""), display


def test_get_child_edu_cost_at_age(page):
    result = page.evaluate(
        f"""() => {{
            const child = {CHILD_PUBLIC_10};
            const ages = [0, 5, 6, 11, 12, 14, 15, 17, 18, 21, 22, 30];
            return ages.map(a => getChildEduCostAtAge(child, a));
        }}"""
    )
    assert result == [0, 0, 35, 35, 54, 54, 51, 51, 61, 61, 0, 0], result


def test_get_total_edu_cost_for_child(page):
    total = page.evaluate(f"getTotalEduCostForChild({CHILD_PUBLIC_10})")
    # ages 10-11 elementary(35x2) + 12-14 middle(54x3) + 15-17 high(51x3) + 18-21 univ(61x4)
    expected = 35 * 2 + 54 * 3 + 51 * 3 + 61 * 4
    assert total == expected, (total, expected)


def test_get_edu_cost_for_year(page):
    val = page.evaluate(
        f"""() => {{
            children = [{CHILD_PUBLIC_10}];
            return getEduCostForYear(15, 10);
        }}"""
    )
    # child is 10 now, year 15 is +5 offset -> age 15 -> high school (public=51)
    assert val == 51, val


MC_BASE_PARAMS = """{
    currentAge: 40, currentAssets: 1000, returnRate: 0.05,
    afterTaxIncome: 500, annualSavings: 120, annualExpense: 400,
    annualSideIncome: 0, annualPension: 180,
    fireAge: 50, fullFireAge: 65, livingCostRatio65: 1.0,
    withdrawalTaxEnabled: false,
    recoveryEnabled: false, recoveryYears: 5
}"""


def test_monte_carlo_deterministic_when_crash_prob_zero(page):
    result = page.evaluate(
        f"""() => {{
            children = [];
            return runMonteCarlo({{ ...{MC_BASE_PARAMS}, crashProb: 0, crashMag: 0.4, numSims: 20 }});
        }}"""
    )
    p10, p50, p90 = result["p10"], result["p50"], result["p90"]
    assert p10 == p50 == p90, "crashProb=0 means every simulated path must be identical"
    assert len(p50) == 100 - 40 + 1
    assert 0 <= result["ruinRate"] <= 1


def test_monte_carlo_percentile_ordering_with_crashes(page):
    result = page.evaluate(
        f"""() => {{
            children = [];
            return runMonteCarlo({{
                ...{MC_BASE_PARAMS}, crashProb: 0.1, crashMag: 0.4, numSims: 300,
                recoveryEnabled: true
            }});
        }}"""
    )
    p10, p50, p90 = result["p10"], result["p50"], result["p90"]
    assert all(p10[i] <= p50[i] <= p90[i] for i in range(len(p50))), "percentiles must stay ordered p10<=p50<=p90"
    assert 0 <= result["ruinRate"] <= 1


def test_monte_carlo_recovery_boost_returns_to_trend(page):
    """One crash in year 0 with a 5-year recovery must land exactly on the no-crash path by year 5."""
    result = page.evaluate(
        f"""() => {{
            children = [];
            const params = {{
                ...{MC_BASE_PARAMS}, afterTaxIncome: 0, annualSavings: 0, annualExpense: 0,
                annualPension: 0, crashMag: 0.4, numSims: 1, recoveryEnabled: true, recoveryYears: 5
            }};
            const orig = Math.random;
            let n = 0;
            Math.random = () => (n++ === 0 ? 0 : 1);  // crash only in the first year
            const crashed = runMonteCarlo({{ ...params, crashProb: 0.5 }});
            Math.random = orig;
            const trend = runMonteCarlo({{ ...params, crashProb: 0 }});
            return {{ crashed: crashed.p50, trend: trend.p50 }};
        }}"""
    )
    assert result["crashed"][0] < result["trend"][0], result
    assert result["crashed"][4] == result["trend"][4], (result["crashed"][:6], result["trend"][:6])


def test_pre_fire_savings_capped_by_surplus(page):
    result = page.evaluate(
        """() => {
            children = [];
            const p = { currentAge: 41, afterTaxIncome: 499, annualSavings: 120, annualExpense: 540,
                        annualSideIncome: 0, annualPension: 0, fireAge: 50, fullFireAge: 65,
                        livingCostRatio65: 1, withdrawalTaxEnabled: false };
            const pick = f => [f.contribution, f.flow, f.displayCashflow];
            return {
                deficit:    pick(calcYearFlow(41, p)),
                deficitTax: pick(calcYearFlow(41, { ...p, withdrawalTaxEnabled: true })),
                partial:    pick(calcYearFlow(41, { ...p, afterTaxIncome: 600 })),
                full:       pick(calcYearFlow(41, { ...p, afterTaxIncome: 800 })),
            };
        }"""
    )
    # surplus -41: nothing is saved, the shortfall is drawn from assets
    assert result["deficit"] == [0, -41, -41], result
    assert result["deficitTax"][0] == 0 and abs(result["deficitTax"][1] + 41 / 0.8) < 1e-9, result
    # surplus 60 < 120: only 60 can be saved
    assert result["partial"] == [60, 60, 0], result
    # surplus 260 >= 120: full 120 saved, 140 left over
    assert result["full"] == [120, 120, 140], result


def test_inflation_slider_sets_real_return(page):
    hint = page.inner_text("#realRateHint")
    assert "4.0%" in hint, hint  # defaults: 5% nominal, 1% inflation -> 1.05/1.01-1 = 3.96%
    page.fill("#currentAssets", "50000")  # large enough that assets never hit 0 at either inflation rate
    final_1pct = parse_man_yen(page.inner_text("#card-final"))
    page.evaluate(
        """() => {
            const el = document.getElementById('inflationRate');
            el.value = 30;
            el.dispatchEvent(new Event('input'));
        }"""
    )
    assert page.inner_text("#inflationRateVal") == "3.0%"
    final_3pct = parse_man_yen(page.inner_text("#card-final"))
    assert final_3pct < final_1pct, (final_1pct, final_3pct)


def test_chart_range_slider_reaches_100(page):
    page.fill("#currentAge", "41")
    state = page.evaluate(
        """() => {
            const s = document.getElementById('chartMaxAgeSlider');
            s.value = 100;
            return { min: s.min, value: s.value };
        }"""
    )
    assert state == {"min": "50", "value": "100"}, state


def test_crash_hint_rare_branch(page):
    page.click("#crashToggle")
    page.evaluate(
        """() => {
            const el = document.getElementById('crashProb');
            el.value = 4;
            el.dispatchEvent(new Event('input'));
        }"""
    )
    assert "稀なケース" in page.inner_text("#crashProbHint")


def test_default_children_on_first_load(page):
    cards = page.query_selector_all(".child-card")
    assert len(cards) == 2, len(cards)
    ages = page.eval_on_selector_all(
        ".child-grid .full-width input[type=number]", "els => els.map(e => e.value)"
    )
    assert ages == ["10", "4"], ages


def test_add_and_remove_child_via_ui(page):
    initial = len(page.query_selector_all(".child-card"))
    page.click("button.btn-add")
    assert len(page.query_selector_all(".child-card")) == initial + 1

    # remove every child, including the ones present at page load
    while page.query_selector_all(".child-card"):
        page.click(".child-card:last-child .btn-remove")
    assert len(page.query_selector_all(".child-card")) == 0

    edu_card = page.inner_text("#card-edu")
    assert edu_card == page.evaluate("formatMan(0)"), edu_card


def test_simulate_wiring_updates_cards_and_table(page):
    page.fill("#currentAge", "30")
    page.fill("#currentAssets", "500")
    page.fill("#annualIncome", "600")
    page.fill("#monthlySavings", "15")
    page.fill("#monthlyExpense", "45")

    expected_target4 = page.evaluate("formatMan(45 * 12 * 25)")
    assert page.inner_text("#card-target4") == expected_target4

    rows = page.query_selector_all("#asset-table-container tbody tr")
    assert len(rows) == 100 - 30 + 1, len(rows)


def test_crash_toggle_shows_ruin_banner(page):
    page.click("#crashToggle")
    banner_text = page.inner_text("#banner")
    assert "資産枯渇リスク" in banner_text, banner_text
    legend_display = page.eval_on_selector("#crashLegend", "el => getComputedStyle(el).display")
    assert legend_display == "flex", legend_display


def test_withdrawal_tax_toggle_scales_target4(page):
    page.fill("#monthlyExpense", "10")
    pre = parse_man_yen(page.inner_text("#card-target4"))
    page.click("#withdrawalTaxToggle")
    post = parse_man_yen(page.inner_text("#card-target4"))
    assert abs(post - pre * 1.25) < 1, (pre, post)


def test_localstorage_persists_across_reload(page):
    page.fill("#currentAge", "36")
    page.reload()
    page.wait_for_function("typeof Chart !== 'undefined'")
    val = page.input_value("#currentAge")
    assert val == "36", val


def test_zero_children_persists_across_reload(page):
    while page.query_selector_all(".child-card"):
        page.click(".child-card:last-child .btn-remove")
    page.reload()
    page.wait_for_function("typeof Chart !== 'undefined'")
    assert len(page.query_selector_all(".child-card")) == 0


TESTS = [
    test_format_man,
    test_calc_after_tax_income,
    test_get_child_edu_cost_at_age,
    test_get_total_edu_cost_for_child,
    test_get_edu_cost_for_year,
    test_monte_carlo_deterministic_when_crash_prob_zero,
    test_monte_carlo_percentile_ordering_with_crashes,
    test_monte_carlo_recovery_boost_returns_to_trend,
    test_pre_fire_savings_capped_by_surplus,
    test_inflation_slider_sets_real_return,
    test_chart_range_slider_reaches_100,
    test_crash_hint_rare_branch,
    test_default_children_on_first_load,
    test_add_and_remove_child_via_ui,
    test_simulate_wiring_updates_cards_and_table,
    test_crash_toggle_shows_ruin_banner,
    test_withdrawal_tax_toggle_scales_target4,
    test_localstorage_persists_across_reload,
    test_zero_children_persists_across_reload,
]


def run_test(browser, fn):
    context = browser.new_context(locale="en-US")
    page = context.new_page()
    console_errors = []
    page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
    page.on("pageerror", lambda exc: console_errors.append(str(exc)))

    try:
        page.goto(HTML_URL)
        page.wait_for_function("typeof Chart !== 'undefined'", timeout=10000)
        fn(page)
        if console_errors:
            raise AssertionError(f"console errors detected: {console_errors}")
        return True, ""
    except AssertionError as e:
        return False, str(e)
    except Exception as e:
        return False, f"ERROR: {e!r}"
    finally:
        context.close()


def main():
    passed = failed = 0
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for fn in TESTS:
            ok, msg = run_test(browser, fn)
            name = fn.__name__
            if ok:
                passed += 1
                print(f"[PASS] {name}")
            else:
                failed += 1
                print(f"[FAIL] {name} - {msg}")
        browser.close()

    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
