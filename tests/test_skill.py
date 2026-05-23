import queue

from config import Permissions
from tools.skill.loader import SkillDef, find_skill, load_skills, substitute_arguments
from tools.skill.executor import execute_skill


def test_load_skills_supports_common_project_dirs(tmp_path, monkeypatch):
    skill_dir = tmp_path / "skills"
    skill_dir.mkdir()
    (skill_dir / "demo.md").write_text(
        """---
name: demo
description: Demo skill
triggers: [demo, do demo]
allowed-tools: [Read, Bash]
arguments: [target]
when-to-use: Testing
---
Run on $TARGET with $ARGUMENTS.
""",
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)

    skills = load_skills()
    demo = next(skill for skill in skills if skill.name == "demo")
    assert demo.source == "project"
    assert demo.triggers == ["demo", "do demo"]
    assert demo.tools == ["Read", "Bash"]
    assert demo.arguments == ["target"]
    assert demo.when_to_use == "Testing"
    assert find_skill("do anything").name == "demo"


def test_substitute_arguments_treats_string_argument_metadata_as_list():
    prompt = "$ARGUMENTS :: $FIRST :: $SECOND"

    assert substitute_arguments(prompt, "alpha beta", ["first", "second"]) == (
        "alpha beta :: alpha :: beta"
    )


def test_execute_skill_defaults_config_and_preserves_permission_mode(monkeypatch):
    captured = {}

    class FakeMultiAgent:
        def run(self, message, config, task):
            captured["message"] = message
            captured["config"] = config
            task.messages.append({"role": "assistant", "content": "done"})

        @staticmethod
        def get_assistant_messages(messages):
            return "\n".join(
                message["content"]
                for message in messages
                if message.get("role") == "assistant" and message.get("content")
            )

    monkeypatch.setattr("agent.MultiAgent", FakeMultiAgent)

    skill = SkillDef(
        name="demo",
        description="Demo",
        triggers=["demo"],
        tools=[],
        prompt="Use $ARGUMENTS",
        file_path="demo.md",
    )

    assert execute_skill(skill, "abc") == "done"
    assert captured["config"]["depth"] == 1
    assert captured["config"]["permission_mode"] == Permissions.AUTO
    assert "Use abc" in captured["message"]


def test_execute_skill_inherits_parent_event_queue(monkeypatch):
    parent_task = type("ParentTask", (), {"event_queue": queue.Queue()})()
    captured = {}

    class FakeMultiAgent:
        def run(self, message, config, task):
            captured["event_queue"] = task.event_queue
            task.result = "ok"

        @staticmethod
        def get_assistant_messages(messages):
            return ""

    monkeypatch.setattr("agent.MultiAgent", FakeMultiAgent)

    skill = SkillDef(
        name="demo",
        description="Demo",
        triggers=["demo"],
        tools=[],
        prompt="Run",
        file_path="demo.md",
    )

    assert execute_skill(skill, config={"depth": 0, "_task": parent_task}) == "ok"
    assert captured["event_queue"] is parent_task.event_queue
