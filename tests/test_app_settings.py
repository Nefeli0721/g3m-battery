"""app_settings 的单元测试（纯逻辑，不碰真实注册表/启动文件夹）。"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app_settings  # noqa: E402


class DefaultsTests(unittest.TestCase):
    def test_defaults_cover_all_switchable_fields(self):
        d = app_settings.defaults()
        for f in app_settings.all_fields():
            if f.kind == "autostart":
                continue
            self.assertIn(f.key, d, f"缺少默认值: {f.key}")
            self.assertEqual(d[f.key], f.default)

    def test_autostart_not_in_defaults(self):
        self.assertNotIn("autostart", app_settings.defaults())


class MergeTests(unittest.TestCase):
    def test_garbage_input_returns_defaults(self):
        self.assertEqual(app_settings.merge(None), app_settings.defaults())
        self.assertEqual(app_settings.merge("oops"), app_settings.defaults())
        self.assertEqual(app_settings.merge([1, 2]), app_settings.defaults())

    def test_unknown_keys_are_dropped(self):
        cfg = app_settings.merge({"nonsense": 1})
        self.assertNotIn("nonsense", cfg)

    def test_legacy_key_is_renamed(self):
        cfg = app_settings.merge({"steam_popup_enabled": False})
        self.assertFalse(cfg["low_battery_popup_enabled"])
        self.assertNotIn("steam_popup_enabled", cfg)

    def test_int_is_clamped(self):
        cfg = app_settings.merge({"interval": 1, "low_battery_threshold": 999})
        self.assertEqual(cfg["interval"], 5)          # 下限
        self.assertEqual(cfg["low_battery_threshold"], 50)  # 上限

    def test_bool_coercion(self):
        cfg = app_settings.merge({"widget_topmost": 0})
        self.assertIs(cfg["widget_topmost"], False)
        cfg = app_settings.merge({"widget_topmost": "x"})
        self.assertIs(cfg["widget_topmost"], True)

    def test_choice_validated(self):
        cfg = app_settings.merge({"curve_range_hours": 12})
        self.assertEqual(cfg["curve_range_hours"], 24)   # 非法值回退默认
        cfg = app_settings.merge({"curve_range_hours": 72})
        self.assertEqual(cfg["curve_range_hours"], 72)

    def test_window_pos_preserved(self):
        cfg = app_settings.merge({"window_pos": [10, 20]})
        self.assertEqual(cfg["window_pos"], [10, 20])


class AutostartPathTests(unittest.TestCase):
    def test_startup_target_is_under_appdata(self):
        target = app_settings.startup_target()
        appdata = os.environ.get("APPDATA", "")
        self.assertTrue(target.startswith(appdata))
        self.assertTrue(target.endswith(".vbs"))


if __name__ == "__main__":
    unittest.main()
