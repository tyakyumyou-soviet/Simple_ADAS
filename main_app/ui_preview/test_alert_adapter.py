import unittest
from types import SimpleNamespace
from alert_adapter import adapt_alert, sides_for_alert


def alert(kind='ldw', level=2, direction='左', target_id=None):
    return SimpleNamespace(kind=kind, level=level, direction=direction,
                           message='警告', target_id=target_id)


class AlertAdapterTest(unittest.TestCase):
    def test_lane_left_and_red_right(self):
        left = adapt_alert(alert())
        self.assertEqual((left.category, left.color, left.direction), ('車線', '黄色', '左'))
        self.assertEqual(sides_for_alert(left), {'左'})
        right = adapt_alert(alert(level=3, direction='右'))
        self.assertEqual(right.color, '赤色')
        self.assertEqual(sides_for_alert(right), {'右'})

    def test_center_and_depth_directions(self):
        center = adapt_alert(alert('person_collision', 3, '正面', 7))
        self.assertEqual(center.category, '人')
        self.assertEqual(sides_for_alert(center), {'左', '右'})
        self.assertEqual(adapt_alert(alert(direction='右前')).direction, '右')

    def test_missing_direction_and_class_are_not_invented(self):
        unknown = adapt_alert(alert('collision', 3, None, 7))
        self.assertEqual(unknown.category, '不明')
        self.assertEqual(unknown.direction, '不明')
        self.assertEqual(sides_for_alert(unknown), set())
        self.assertEqual(adapt_alert(alert('collision', 3, '左', 7), {7: 'car'}).category, '車両')

    def test_informational_alert_does_not_blink(self):
        info = adapt_alert(alert('front_start', 1, '中央'))
        self.assertEqual(info.color, '情報')
        self.assertEqual(sides_for_alert(info), set())

    def test_unknown_level_does_not_blink(self):
        unknown = adapt_alert(alert(level=99))
        self.assertEqual(unknown.color, '不明')
        self.assertEqual(sides_for_alert(unknown), set())
