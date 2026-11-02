from src.alert.alert_manager import AlertManager
from src.types import Alert


def test_alert_manager_cooldown() -> None:
    manager = AlertManager()
    alert = Alert("collision", 3, 1, "collision", None)
    assert len(manager.update([alert], 0.0)) == 1
    assert len(manager.update([alert], 0.1)) == 1
    assert len(manager.update([alert], 2.0)) == 1
