from uniclaw.tools.skill.loader import find_skill, load_skills, substitute_arguments


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

    skills = load_skills(root_dir=tmp_path)
    demo = next(skill for skill in skills if skill.name == "demo")
    assert demo.source == "project"
    assert demo.triggers == ["demo", "do demo"]
    assert demo.tools == ["Read", "Bash"]
    assert demo.arguments == ["target"]
    assert demo.when_to_use == "Testing"
    assert find_skill(root_dir=tmp_path, query="do anything").name == "demo"


def test_substitute_arguments_treats_string_argument_metadata_as_list():
    prompt = "$ARGUMENTS :: $FIRST :: $SECOND"

    assert substitute_arguments(prompt, "alpha beta", ["first", "second"]) == (
        "alpha beta :: alpha :: beta"
    )
