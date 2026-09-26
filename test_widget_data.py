# -*- coding: utf-8 -*-
import os
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel

from codex_usage_widget import (
    DataStore,
    QuotaBar,
    THEMES,
    UsageCard,
    format_reset_credit_status,
    is_free_plan,
    reset_countdown,
)


QT_APP = QApplication.instance() or QApplication([])


class DataStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp_dir.name)
        now_ms = int(time.time() * 1000)
        (self.data_dir / "config.json").write_text(json.dumps({
            "activeCodexAccountId": "pool-a",
            "codexAccounts": [
                {"id": "pool-a", "email": "test-email-1", "plan": "plus", "logLabel": "alpha"},
                {"id": "pool-b", "email": "test-email-2", "plan": "plus", "logLabel": "beta"},
            ],
        }), encoding="utf-8")
        (self.data_dir / "codex-quota-cache.json").write_text(json.dumps({"quotas": {
            "pool-a": {"shortPercent": 10, "weeklyPercent": 20, "resetCredits": 2},
            "pool-b": {"shortPercent": 30, "weeklyPercent": 40},
            "__main__": {"shortPercent": 50, "weeklyPercent": 60},
        }}), encoding="utf-8")
        rows = [
            {"timestamp": now_ms, "provider": "openai-alpha", "usage": {"inputTokens": 10, "outputTokens": 2, "cachedInputTokens": 5}, "status": 200, "model": "alpha-model"},
            {"timestamp": now_ms, "provider": "openai-beta", "accountLogLabel": "beta", "usage": {"inputTokens": 20, "outputTokens": 3}, "status": 500, "model": "beta-model"},
            {"timestamp": now_ms, "provider": "openai", "usage": {"inputTokens": 30, "outputTokens": 4}, "status": 200, "model": "main-model"},
            {"timestamp": now_ms, "provider": "other", "usage": {"inputTokens": 999}},
            {"timestamp": now_ms - 2 * 24 * 3600 * 1000, "provider": "openai-alpha", "usage": {"inputTokens": 999}},
            "not-json",
        ]
        (self.data_dir / "usage.jsonl").write_text("\n".join(
            row if isinstance(row, str) else json.dumps(row) for row in rows
        ), encoding="utf-8")
        self.store = DataStore(self.data_dir)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_stats_are_selected_by_account_label(self) -> None:
        alpha = self.store.snapshot("pool-a")["today"]
        beta = self.store.snapshot("pool-b")["today"]
        main = self.store.snapshot("__main__")["today"]

        self.assertEqual((alpha.requests, alpha.tokens_in, alpha.tokens_out, alpha.tokens_cached), (1, 10, 2, 5))
        self.assertEqual(alpha.models, {"alpha-model": 1})
        self.assertTrue(self.store.snapshot("pool-a")["is_active"])
        self.assertFalse(self.store.snapshot("pool-b")["is_active"])
        self.assertEqual((beta.requests, beta.tokens_in, beta.tokens_out, beta.errors), (1, 20, 3, 1))
        self.assertEqual(main.models, {"main-model": 1})

        # An unchanged JSON cache must remain available on subsequent reads.
        second_alpha = self.store.snapshot("pool-a")["today"]
        self.assertEqual(second_alpha.tokens_in, alpha.tokens_in)

    def test_usage_rewrite_with_same_size_rebuilds_tail(self) -> None:
        self.store.snapshot("pool-a")
        usage_path = self.data_dir / "usage.jsonl"
        content = usage_path.read_text(encoding="utf-8")
        usage_path.write_text(content.replace('"inputTokens": 10', '"inputTokens": 90'), encoding="utf-8")

        self.store.invalidate("usage.jsonl")
        alpha = self.store.snapshot("pool-a", force_usage=True)["today"]
        self.assertEqual(alpha.tokens_in, 90)

    def test_usage_rewrite_with_larger_file_rebuilds_tail(self) -> None:
        self.store.snapshot("__main__")
        usage_path = self.data_dir / "usage.jsonl"
        now_ms = int(time.time() * 1000)
        rows = [
            {"timestamp": now_ms, "provider": "openai", "usage": {"inputTokens": 90}},
            {"timestamp": now_ms, "provider": "openai", "usage": {"inputTokens": 20}},
        ]
        usage_path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")

        self.store.invalidate("usage.jsonl")
        main = self.store.snapshot("__main__", force_usage=True)["today"]
        self.assertEqual(main.tokens_in, 110)

    def test_invalidated_json_keeps_last_valid_cache(self) -> None:
        before = self.store.snapshot("pool-a")
        (self.data_dir / "codex-quota-cache.json").write_text("{", encoding="utf-8")
        self.store.invalidate("codex-quota-cache.json")

        after = self.store.snapshot("pool-a")
        self.assertEqual(after["email"], before["email"])
        self.assertEqual(after["short_percent"], before["short_percent"])

    def test_countdown_rolls_recurring_windows_forward(self) -> None:
        self.assertEqual(reset_countdown(None, 3600, now=100), "重置 —")
        self.assertEqual(reset_countdown(110, 3600, now=100), "重置 10 秒后")
        self.assertEqual(reset_countdown(90, 3600, now=100), "重置 60 分钟后")

    def test_reset_credit_details_are_isolated_by_count_and_account(self) -> None:
        cache_path = self.data_dir / "reset-credit-details-cache.json"
        cache_path.write_text(json.dumps({
            "schemaVersion": 1,
            "producerVersion": "2.60.0",
            "revision": 3,
            "accounts": {
                "pool-a": {
                    "availableCount": 2,
                    "updatedAt": 1_700_000_000_000,
                    "credits": [
                        {"expiresAt": "2030-01-02T03:04:05Z"},
                        {"expiresAt": "2030-01-01T03:04:05Z"},
                    ],
                },
            },
        }), encoding="utf-8")

        snap = self.store.snapshot("pool-a")
        self.assertEqual(len(snap["reset_credit_details"]), 2)
        self.assertTrue(snap["reset_credit_cache_ok"])
        self.assertLess(snap["reset_credit_details"][0]["expires_at"],
                        snap["reset_credit_details"][1]["expires_at"])

        # A quota count change invalidates old detail rows until OpenCodex writes
        # the matching cache entry; another account cannot see pool-a's rows.
        self.assertFalse(self.store.snapshot("pool-b")["reset_credit_cache_ok"])
        self.assertFalse(self.store.reset_credit_details("pool-a", 1)[3])

    def test_reset_credit_mismatch_is_shown_as_waiting_for_sync(self) -> None:
        cache_path = self.data_dir / "reset-credit-details-cache.json"
        cache_path.write_text(json.dumps({
            "schemaVersion": 1,
            "producerVersion": "2.60.0",
            "revision": 1,
            "accounts": {
                "pool-a": {
                    "availableCount": 1,
                    "updatedAt": 1_700_000_000_000,
                    "credits": [{"expiresAt": "2030-01-01T03:04:05Z"}],
                },
            },
        }), encoding="utf-8")

        snap = self.store.snapshot("pool-a")

        self.assertEqual(snap["reset_credits"], 2)
        self.assertFalse(snap["reset_credit_cache_ok"])
        self.assertEqual(snap["reset_credit_details"], [])
        self.assertIn("数量不一致", snap["reset_credit_notice"])
        self.assertIn(
            "数量不一致",
            format_reset_credit_status(
                snap["reset_credit_updated"],
                snap["reset_credit_failed"],
                snap["reset_credit_notice"],
            ),
        )

    def test_reset_credit_cache_requires_complete_details(self) -> None:
        cache_path = self.data_dir / "reset-credit-details-cache.json"
        cache_path.write_text(json.dumps({
            "schemaVersion": 1,
            "producerVersion": "2.60.0",
            "revision": 1,
            "accounts": {
                "pool-a": {
                    "availableCount": 2,
                    "updatedAt": 1_700_000_000_000,
                    "credits": [{"expiresAt": "2030-01-01T03:04:05Z"}],
                },
            },
        }), encoding="utf-8")

        snap = self.store.snapshot("pool-a")

        self.assertFalse(snap["reset_credit_cache_ok"])
        self.assertEqual(snap["reset_credit_details"], [])
        self.assertIn("详情不完整", snap["reset_credit_notice"])

    def test_reset_credit_status_explains_freshness_and_failure(self) -> None:
        self.assertEqual(format_reset_credit_status(None, None), "详情尚未同步")
        self.assertIn("最近同步", format_reset_credit_status(1_700_000_000, None))
        self.assertIn("保留上次有效内容", format_reset_credit_status(1_700_000_000, 1_700_000_001))
        self.assertEqual(format_reset_credit_status(None, None, "详情缓存格式不兼容"), "提示：详情缓存格式不兼容")


class QuotaBarTests(unittest.TestCase):
    def setUp(self) -> None:
        self.bar = QuotaBar("5 小时窗口剩余", period=5 * 3600)
        self.bar.apply_theme(THEMES["light"])

    def tearDown(self) -> None:
        self.bar.close()
        self.bar.deleteLater()
        QT_APP.processEvents()

    def test_set_value_immediately_shows_countdown(self) -> None:
        with patch("codex_usage_widget.time.time", return_value=100):
            self.bar.set_value(20, 7_300)

        self.assertEqual(self.bar._reset_label.text(), "重置 2 小时后")

    def test_set_value_refreshes_countdown_when_reset_time_changes(self) -> None:
        with patch("codex_usage_widget.time.time", return_value=100):
            self.bar.set_value(20, 7_300)
            self.assertEqual(self.bar._reset_label.text(), "重置 2 小时后")

            self.bar.set_value(30, 160)

        self.assertEqual(self.bar._reset_label.text(), "重置 1 分钟后")

    def test_unavailable_state_is_empty_and_can_restore_paid_quota(self) -> None:
        with patch("codex_usage_widget.time.time", return_value=100):
            self.bar.set_value(20, 7_300)
            self.bar.set_unavailable()

        self.assertEqual(self.bar._pct_label.text(), "无额度")
        self.assertEqual(self.bar._bar.value(), 0)
        self.assertFalse(self.bar._bar.isEnabled())
        self.assertEqual(self.bar._reset_label.text(), "")

        with patch("codex_usage_widget.time.time", return_value=100):
            self.bar.set_value(30, 7_300)

        self.assertEqual(self.bar._pct_label.text(), "70%")
        self.assertTrue(self.bar._bar.isEnabled())


class QuotaDisplayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.card = UsageCard.__new__(UsageCard)
        self.card._theme_key = "light"
        self.card._short_bar = QuotaBar("5 小时窗口剩余", period=5 * 3600)
        self.card._weekly_bar = QuotaBar("每周窗口剩余", period=7 * 24 * 3600)
        self.card._short_bar.apply_theme(THEMES["light"])
        self.card._weekly_bar.apply_theme(THEMES["light"])
        self.card._big_short = QLabel()
        self.card._big_weekly = QLabel()
        self.card._big_reset_labels = [QLabel("旧倒计时"), QLabel("旧倒计时")]

    def tearDown(self) -> None:
        for bar in (self.card._short_bar, self.card._weekly_bar):
            bar.close()
            bar.deleteLater()
        for label in (*self.card._big_reset_labels, self.card._big_short, self.card._big_weekly):
            label.deleteLater()
        QT_APP.processEvents()

    def test_free_plan_is_case_insensitive_and_shows_no_quota(self) -> None:
        self.assertTrue(is_free_plan(" FREE "))
        self.assertFalse(is_free_plan("plus"))

        self.card._update_quota_display({
            "plan": " FREE ",
            "short_percent": 50,
            "short_reset": 7_300,
            "weekly_percent": 60,
            "weekly_reset": 7_300,
        })
        self.card._update_big_countdowns({
            "plan": " FREE ",
            "short_reset": 7_300,
            "weekly_reset": 7_300,
        })

        self.assertEqual(self.card._short_bar._pct_label.text(), "无额度")
        self.assertEqual(self.card._weekly_bar._pct_label.text(), "无额度")
        self.assertFalse(self.card._short_bar._bar.isEnabled())
        self.assertFalse(self.card._weekly_bar._bar.isEnabled())
        self.assertEqual(self.card._big_short.text(), "无额度")
        self.assertEqual(self.card._big_weekly.text(), "无额度")
        self.assertEqual(self.card._big_reset_labels[0].text(), "")
        self.assertEqual(self.card._big_reset_labels[1].text(), "")

    def test_paid_plan_keeps_percentage_display(self) -> None:
        with patch("codex_usage_widget.time.time", return_value=100):
            self.card._update_quota_display({
                "plan": "plus",
                "short_percent": 20,
                "short_reset": 7_300,
                "weekly_percent": 30,
                "weekly_reset": 7_300,
            })

        self.assertEqual(self.card._short_bar._pct_label.text(), "80%")
        self.assertEqual(self.card._weekly_bar._pct_label.text(), "70%")
        self.assertTrue(self.card._short_bar._bar.isEnabled())
        self.assertTrue(self.card._weekly_bar._bar.isEnabled())
        self.assertEqual(self.card._big_short.text(), "80%")
        self.assertEqual(self.card._big_weekly.text(), "70%")


if __name__ == "__main__":
    unittest.main()
