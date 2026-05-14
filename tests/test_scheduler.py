"""
定时任务调度器的单元测试
"""
import json
import pytest
from unittest.mock import patch
from pathlib import Path
from datetime import datetime, timedelta

from scheduler import Scheduler, _parse_schedule


@pytest.fixture(autouse=True)
def tmp_config(tmp_path):
    """每个测试使用独立的临时配置文件"""
    fake_dir = tmp_path / ".UniClaw"
    fake_dir.mkdir()
    config_file = fake_dir / "scheduler.json"
    with patch.object(Scheduler, "_instance", None):
        with patch("scheduler.get_app_dir", return_value=fake_dir):
            yield config_file


@pytest.fixture
def scheduler():
    return Scheduler.get_instance()


class TestParseSchedule:
    """调度字符串解析测试"""

    def test_every_seconds(self):
        result = _parse_schedule("every 30s")
        assert result == timedelta(seconds=30)

    def test_every_minutes(self):
        result = _parse_schedule("every 5m")
        assert result == timedelta(minutes=5)

    def test_every_hours(self):
        result = _parse_schedule("every 1h")
        assert result == timedelta(hours=1)

    def test_every_days(self):
        result = _parse_schedule("every 1d")
        assert result == timedelta(days=1)

    def test_every_case_insensitive(self):
        assert _parse_schedule("every 1H") == timedelta(hours=1)
        assert _parse_schedule("every 1M") == timedelta(minutes=1)

    def test_every_with_spaces(self):
        assert _parse_schedule("  every 30m  ") == timedelta(minutes=30)

    def test_at_datetime(self):
        result = _parse_schedule("at 2026-05-10 14:00")
        assert isinstance(result, datetime)
        assert result == datetime(2026, 5, 10, 14, 0)

    def test_invalid_format(self):
        assert _parse_schedule("invalid") is None
        assert _parse_schedule("every") is None
        assert _parse_schedule("every abc") is None
        assert _parse_schedule("at 2026-05-10") is None


class TestSchedulerCRUD:
    """调度器 CRUD 操作测试"""

    def test_add_task(self, scheduler):
        scheduler.add_task("test-1", "测试任务", "every 1h", "shell: echo hello")
        tasks = scheduler.list_tasks()
        assert len(tasks) == 1
        assert tasks[0]["id"] == "test-1"
        assert tasks[0]["name"] == "测试任务"
        assert tasks[0]["schedule"] == "every 1h"
        assert tasks[0]["action"] == "shell: echo hello"
        assert tasks[0]["enabled"] is True

    def test_add_task_duplicate_raises(self, scheduler):
        scheduler.add_task("test-1", "", "every 1h", "shell: echo hello")
        with pytest.raises(ValueError, match="已存在"):
            scheduler.add_task("test-1", "", "every 30m", "shell: echo world")

    def test_add_task_invalid_schedule(self, scheduler):
        with pytest.raises(ValueError, match="无效的调度格式"):
            scheduler.add_task("test-1", "", "invalid", "shell: echo hello")

    def test_remove_task(self, scheduler):
        scheduler.add_task("test-1", "", "every 1h", "shell: echo hello")
        assert scheduler.remove_task("test-1") is True
        assert scheduler.list_tasks() == []

    def test_remove_task_not_found(self, scheduler):
        assert scheduler.remove_task("nonexistent") is False

    def test_toggle_task(self, scheduler):
        scheduler.add_task("test-1", "", "every 1h", "shell: echo hello")
        assert scheduler.toggle_task("test-1", False) is True
        tasks = scheduler.list_tasks()
        assert tasks[0]["enabled"] is False
        assert scheduler.toggle_task("test-1", True) is True
        tasks = scheduler.list_tasks()
        assert tasks[0]["enabled"] is True

    def test_toggle_task_not_found(self, scheduler):
        assert scheduler.toggle_task("nonexistent", True) is False

    def test_persistence(self, scheduler, tmp_config):
        scheduler.add_task("test-1", "持久化测试", "every 1h", "shell: echo hello")
        # 直接读文件验证持久化
        data = json.loads(tmp_config.read_text(encoding="utf-8"))
        assert "test-1" in data["tasks"]
        assert data["tasks"]["test-1"]["name"] == "持久化测试"


class TestSchedulerExecution:
    """调度器执行逻辑测试"""

    def test_recurring_task_runs_when_due(self, scheduler):
        scheduler.add_task("test-1", "", "every 1h", "shell: echo hello")
        scheduler._config["tasks"]["test-1"]["last_run"] = (
            datetime.now() - timedelta(hours=2)
        ).isoformat(timespec="seconds")
        scheduler.save_config()

        scheduler._check_and_run_tasks()

        tasks = scheduler.list_tasks()
        assert tasks[0]["last_run"] is not None

    def test_recurring_task_not_runs_when_not_due(self, scheduler):
        scheduler.add_task("test-1", "", "every 1h", "shell: echo hello")
        now_str = datetime.now().isoformat(timespec="seconds")
        scheduler._config["tasks"]["test-1"]["last_run"] = now_str
        scheduler.save_config()

        scheduler._check_and_run_tasks()

        # last_run 应该没变（没执行）
        tasks = scheduler.list_tasks()
        assert tasks[0]["last_run"] == now_str

    def test_one_shot_task_runs_at_time(self, scheduler):
        past_time = (datetime.now() - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M")
        scheduler.add_task("test-1", "", f"at {past_time}", "shell: echo hello")

        scheduler._check_and_run_tasks()

        tasks = scheduler.list_tasks()
        assert tasks[0]["last_run"] is not None
        assert tasks[0]["enabled"] is False

    def test_one_shot_task_not_runs_before_time(self, scheduler):
        future_time = (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
        scheduler.add_task("test-1", "", f"at {future_time}", "shell: echo hello")

        scheduler._check_and_run_tasks()

        tasks = scheduler.list_tasks()
        assert tasks[0]["last_run"] is None
        assert tasks[0]["enabled"] is True

    def test_disabled_task_skipped(self, scheduler):
        scheduler.add_task("test-1", "", "every 1h", "shell: echo hello")
        scheduler.toggle_task("test-1", False)

        scheduler._check_and_run_tasks()

        tasks = scheduler.list_tasks()
        assert tasks[0]["last_run"] is None


class TestSchedulerSingleton:
    """单例测试"""

    def test_same_instance(self):
        a = Scheduler.get_instance()
        b = Scheduler.get_instance()
        assert a is b


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
