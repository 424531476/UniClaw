"""
config.py 模块的单元测试

测试配置加载、保存和管理功能
"""
import pytest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from uniclaw.config import (
    Permissions,
    AppConfig,
    get_config_path,
    is_first_launch,
    _load_settings_json,
    _save_settings_json,
    save_config,
    load_config,
    create_sub_agent_config,
)


class TestPermissions:
    """Permissions 枚举测试"""

    def test_values(self):
        """测试枚举值"""
        assert Permissions.AUTO == "auto"
        assert Permissions.MANUAL == "manual"
        assert Permissions.ACCEPT_ALL == "accept-all"
        assert Permissions.PLAN == "plan"


class TestAppConfig:
    """AppConfig 数据类测试"""

    def test_default_values(self):
        """测试默认值"""
        config = AppConfig()
        assert config.OPENAI_API_KEY == ""
        assert config.OPENAI_BASE_URL == "https://api.openai.com/v1"
        assert config.model_name == ""
        assert config.mini_model_name == ""
        assert config.multimodal_model_name is None
        assert config.temperature == 0.7
        assert config.max_tokens is None
        assert config.top_p is None
        assert config.proxy_url == ""
        assert config.max_agent_depth == 3
        assert config.permission_timeout == 300
        assert config.permission_mode == Permissions.AUTO
        assert config.verbose is False
        assert config.depth == 0
        assert config.workspace == []
        assert config.writable_dirs == []
        assert config.interactive is True

    def test_custom_values(self):
        """测试自定义值"""
        config = AppConfig(
            OPENAI_API_KEY="test-key",
            model_name="gpt-4",
            temperature=0.5,
            permission_mode=Permissions.MANUAL,
        )
        assert config.OPENAI_API_KEY == "test-key"
        assert config.model_name == "gpt-4"
        assert config.temperature == 0.5
        assert config.permission_mode == Permissions.MANUAL

    def test_root_dir_property(self):
        """测试 root_dir 属性"""
        config = AppConfig()
        mock_session = MagicMock()
        mock_session.root_dir = Path("/test/root")
        mock_agent = MagicMock()
        mock_agent.session = mock_session
        config.current_agent = mock_agent

        assert config.root_dir == Path("/test/root")

    def test_create_child_config(self):
        """测试创建子配置"""
        config = AppConfig()
        mock_session = MagicMock()
        mock_session.root_dir = Path("/test/root")
        mock_agent = MagicMock()
        mock_agent.session = mock_session
        config.current_agent = mock_agent
        config.OPENAI_API_KEY = "test-key"
        config.model_name = "gpt-4"

        with patch("uniclaw.tools.session.session.Session") as MockSession, \
             patch("uniclaw.agent.AgentTask") as MockAgentTask:
            MockSession.return_value = MagicMock()
            MockAgentTask.return_value = MagicMock()

            child_config = config.create_child_config("child", "test prompt")

            assert child_config.depth == 1
            assert child_config.OPENAI_API_KEY == "test-key"
            assert child_config.model_name == "gpt-4"
            assert child_config.parent_agent == mock_agent


class TestGetConfigPath:
    """get_config_path 函数测试"""

    def test_project_path_exists(self):
        """测试项目级配置存在"""
        with patch("uniclaw.context.get_app_dir") as mock_get_app_dir:
            mock_project_dir = MagicMock()
            mock_project_path = MagicMock()
            mock_project_path.exists.return_value = True
            mock_project_dir.__truediv__ = MagicMock(return_value=mock_project_path)
            mock_get_app_dir.return_value = mock_project_dir

            result = get_config_path()
            assert result == mock_project_path

    def test_fallback_to_user_path(self):
        """测试回退到用户级配置"""
        with patch("uniclaw.context.get_app_dir") as mock_get_app_dir:
            mock_project_dir = MagicMock()
            mock_project_path = MagicMock()
            mock_project_path.exists.return_value = False
            mock_project_dir.__truediv__ = MagicMock(return_value=mock_project_path)

            mock_user_dir = MagicMock()
            mock_user_path = MagicMock()
            mock_user_dir.__truediv__ = MagicMock(return_value=mock_user_path)

            def side_effect(path):
                if path == Path.cwd():
                    return mock_project_dir
                return mock_user_dir

            mock_get_app_dir.side_effect = side_effect

            result = get_config_path()
            assert result == mock_user_path


class TestIsFirstLaunch:
    """is_first_launch 函数测试"""

    def test_config_exists(self):
        """测试配置文件存在"""
        with patch("uniclaw.config.get_config_path") as mock_get_path:
            mock_path = MagicMock()
            mock_path.exists.return_value = True
            mock_get_path.return_value = mock_path

            assert is_first_launch() is False

    def test_config_not_exists(self):
        """测试配置文件不存在"""
        with patch("uniclaw.config.get_config_path") as mock_get_path:
            mock_path = MagicMock()
            mock_path.exists.return_value = False
            mock_get_path.return_value = mock_path

            assert is_first_launch() is True


class TestLoadSettingsJson:
    """_load_settings_json 函数测试"""

    def test_load_from_file(self):
        """测试从文件加载"""
        test_data = {
            "OPENAI_API_KEY": "test-key",
            "model_name": "gpt-4",
        }

        with patch("uniclaw.config.get_config_path") as mock_get_path:
            mock_path = MagicMock()
            mock_path.exists.return_value = True
            mock_path.read_text.return_value = json.dumps(test_data)
            mock_get_path.return_value = mock_path

            result = _load_settings_json()
            assert result["OPENAI_API_KEY"] == "test-key"
            assert result["model_name"] == "gpt-4"

    def test_file_not_exists(self):
        """测试文件不存在"""
        with patch("uniclaw.config.get_config_path") as mock_get_path:
            mock_path = MagicMock()
            mock_path.exists.return_value = False
            mock_get_path.return_value = mock_path

            with patch.dict("os.environ", {}, clear=True):
                result = _load_settings_json()
                assert "temperature" in result
                assert result["temperature"] == 0.7

    def test_invalid_json(self):
        """测试无效 JSON"""
        with patch("uniclaw.config.get_config_path") as mock_get_path:
            mock_path = MagicMock()
            mock_path.exists.return_value = True
            mock_path.read_text.return_value = "invalid json"
            mock_get_path.return_value = mock_path

            with patch.dict("os.environ", {}, clear=True):
                result = _load_settings_json()
                assert "temperature" in result

    def test_env_fallback(self):
        """测试环境变量兜底"""
        with patch("uniclaw.config.get_config_path") as mock_get_path:
            mock_path = MagicMock()
            mock_path.exists.return_value = False
            mock_get_path.return_value = mock_path

            with patch.dict("os.environ", {
                "OPENAI_API_KEY": "env-key",
                "OPENAI_BASE_URL": "https://env.api.com/v1/",
            }):
                result = _load_settings_json()
                assert result["OPENAI_API_KEY"] == "env-key"
                assert result["OPENAI_BASE_URL"] == "https://env.api.com/v1/"

    def test_mini_model_default(self):
        """测试 mini_model_name 默认等于 model_name"""
        with patch("uniclaw.config.get_config_path") as mock_get_path:
            mock_path = MagicMock()
            mock_path.exists.return_value = True
            mock_path.read_text.return_value = json.dumps({
                "model_name": "gpt-4",
            })
            mock_get_path.return_value = mock_path

            result = _load_settings_json()
            assert result["mini_model_name"] == "gpt-4"


class TestSaveSettingsJson:
    """_save_settings_json 函数测试"""

    def test_save_to_file(self):
        """测试保存到文件"""
        test_data = {"key": "value"}

        with patch("uniclaw.config.get_config_path") as mock_get_path:
            mock_path = MagicMock()
            mock_parent = MagicMock()
            mock_path.parent = mock_parent
            mock_get_path.return_value = mock_path

            _save_settings_json(test_data)

            mock_parent.mkdir.assert_called_once_with(parents=True, exist_ok=True)
            mock_path.write_text.assert_called_once()


class TestSaveConfig:
    """save_config 函数测试"""

    def test_save_config(self):
        """测试保存配置"""
        config = AppConfig(
            OPENAI_API_KEY="test-key",
            model_name="gpt-4",
            temperature=0.5,
        )

        with patch("uniclaw.config.get_config_path") as mock_get_path:
            mock_path = MagicMock()
            mock_parent = MagicMock()
            mock_path.parent = mock_parent
            mock_get_path.return_value = mock_path

            save_config(config)

            mock_parent.mkdir.assert_called_once_with(parents=True, exist_ok=True)
            mock_path.write_text.assert_called_once()

            # 验证写入的内容
            written_content = mock_path.write_text.call_args[0][0]
            written_data = json.loads(written_content)
            assert written_data["OPENAI_API_KEY"] == "test-key"
            assert written_data["model_name"] == "gpt-4"
            assert written_data["temperature"] == 0.5


class TestLoadConfig:
    """load_config 函数测试"""

    def test_load_config(self):
        """测试加载配置"""
        test_data = {
            "OPENAI_API_KEY": "test-key",
            "OPENAI_BASE_URL": "https://api.openai.com/v1",
            "model_name": "gpt-4",
            "mini_model_name": "gpt-4-mini",
            "temperature": 0.5,
        }

        with patch("uniclaw.tools.session.session.Session") as MockSession, \
             patch("uniclaw.agent.AgentTask") as MockAgentTask, \
             patch("uniclaw.tools.todolist.TodoList") as MockTodoList, \
             patch("uniclaw.config._load_settings_json") as mock_load:
            MockSession.return_value = MagicMock()
            MockAgentTask.return_value = MagicMock()
            MockTodoList.return_value = MagicMock()
            mock_load.return_value = test_data

            mock_spinner = MagicMock()
            config = load_config(Path("/test/root"), mock_spinner)

            assert config.OPENAI_API_KEY == "test-key"
            assert config.model_name == "gpt-4"
            assert config.temperature == 0.5


class TestCreateSubAgentConfig:
    """create_sub_agent_config 函数测试"""

    def test_create_sub_agent_config(self):
        """测试创建子代理配置"""
        with patch("uniclaw.config.load_config") as mock_load:
            mock_config = MagicMock()
            mock_config.current_agent = MagicMock()
            mock_load.return_value = mock_config

            result = create_sub_agent_config(
                Path("/test/root"),
                "sub-agent",
                "test prompt",
                model_name="gpt-4",
            )

            assert mock_config.current_agent.name == "sub-agent"
            assert mock_config.current_agent.prompt == "test prompt"
            assert mock_config.depth == 1
            assert mock_config.model_name == "gpt-4"

    def test_without_model_name(self):
        """测试不指定模型名称"""
        with patch("uniclaw.config.load_config") as mock_load:
            mock_config = MagicMock()
            mock_config.current_agent = MagicMock()
            mock_config.model_name = "original-model"
            mock_load.return_value = mock_config

            result = create_sub_agent_config(
                Path("/test/root"),
                "sub-agent",
                "test prompt",
            )

            assert mock_config.model_name == "original-model"
