import pytest
from monetization_status import check_infrastructure_status

def test_infrastructure_status():
    status = check_infrastructure_status()
    assert status["project"] == "test-bot-499814"
    assert status["billing_active"] is False
    assert status["state"] == "BLOQUE_INFRA_FACTURATION"
    assert status["new_applications"] == 0
    assert status["new_verified_payouts"] == 0
