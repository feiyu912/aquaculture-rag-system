from app.retrieval.entity_checks import (
    ForecastDoc,
    StandardDoc,
    evaluate,
    extract_codes,
    extract_province,
    normalize_code,
)

STANDARDS = [
    StandardDoc(
        code=normalize_code("DB22/T 3310-2021"),
        title="DB22/T 3310-2021 池塘生态养殖水质调控技术规程",
        region="吉林省",
        effective_year=2021,
        species=["通用"],
        status=None,
    ),
    StandardDoc(
        code=normalize_code("DB22/T 1880-2014"),
        title="DB22/T 1880-2014 越冬池水质管理",
        region="吉林省",
        effective_year=2014,
        species=["通用"],
        status="废止",
    ),
]
FORECASTS = [
    ForecastDoc(2026, 10, "湖北省", "2026年10月湖北省水产养殖病害预测预报"),
    ForecastDoc(2025, 4, "山东省", "2025年4月山东省水产养殖病害预测预报"),
]


def test_code_space_and_dash_variants_are_equal():
    assert normalize_code("DB22/T 3310—2021") == normalize_code("DB22/T3310-2021")
    assert extract_codes("《DB22/T3310-2021》对 6.1 的要求") == ["DB22/T3310-2021"]


def test_province_short_form():
    assert extract_province("内蒙地区池塘") == "内蒙古自治区"


def test_unknown_standard_is_rejected():
    violation = evaluate("DB88/T 1234-2024 的投苗密度是多少", standards=STANDARDS, forecasts=[])
    assert violation is not None and violation.reason == "standard_not_found"


def test_repealed_standard_is_rejected():
    violation = evaluate("DB22/T 1880-2014 的要求", standards=STANDARDS, forecasts=[])
    assert violation is not None and violation.reason == "standard_not_current"


def test_region_mismatch_is_rejected():
    violation = evaluate(
        "DB22/T 3310-2021 中广东省池塘的溶解氧限值",
        standards=STANDARDS,
        forecasts=[],
    )
    assert violation is not None and violation.reason == "region_mismatch"


def test_effective_year_mismatch_is_rejected():
    violation = evaluate(
        "DB22/T 3310-2021 于 2025 年实施，具体指标是什么",
        standards=STANDARDS,
        forecasts=[],
    )
    assert violation is not None and violation.reason == "effective_date_mismatch"


def test_existing_forecast_passes():
    violation = evaluate(
        "2026年10月湖北省水产养殖病害预测预报有哪些",
        standards=STANDARDS,
        forecasts=FORECASTS,
    )
    assert violation is None


def test_missing_forecast_is_rejected():
    violation = evaluate(
        "2027年3月海南省水产养殖病害预测预报有哪些",
        standards=STANDARDS,
        forecasts=FORECASTS,
    )
    assert violation is not None and violation.reason == "forecast_not_found"


def test_numeric_question_without_numbers_is_rejected():
    violation = evaluate(
        "DB22/T 3310-2021 中溶解氧应维持多少",
        standards=STANDARDS,
        forecasts=[],
        doc_title="DB22/T 3310-2021 池塘生态养殖水质调控技术规程",
        evidence_text="应保持适宜水平。",
    )
    assert violation is not None and violation.reason == "no_numeric_evidence"


def test_species_absent_from_document_is_rejected():
    violation = evaluate(
        "DB22/T 3310-2021 中凡纳滨对虾的投喂量是多少",
        standards=STANDARDS,
        forecasts=[],
        doc_title="DB22/T 3310-2021 池塘生态养殖水质调控技术规程",
        query_species=["凡纳滨对虾"],
        evidence_text="投喂应定时定量。",
    )
    assert violation is not None and violation.reason == "species_not_in_evidence"