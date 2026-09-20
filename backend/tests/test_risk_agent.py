"""Test sederhana Risk Prediction Agent memakai data seed_data yang sudah ada."""

from backend.agents.risk_prediction import calculate_risk_score


def test_calculate_risk_score_bantul_dini_hari():
    result = calculate_risk_score("Bantul", "dini_hari")
    print(f"Hasil calculate_risk_score: {result}")

    assert result["area"] == "Bantul"
    assert result["time_slot"] == "dini_hari"
    assert result["score"] > 0
