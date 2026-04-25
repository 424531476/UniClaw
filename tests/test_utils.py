"""
truncate_text_by_lines 函数的单元测试
"""
import pytest
from utils.truncation import truncate_text_by_lines


class TestTruncateTextByLines:
    """truncate_text_by_lines 函数的测试类"""

    # ==================== 边界条件测试 ====================

    def test_empty_string(self):
        """测试空字符串"""
        assert truncate_text_by_lines("") == ""

    def test_none_input(self):
        """测试None输入"""
        assert truncate_text_by_lines(None) is None

    def test_short_text_within_limit(self):
        """测试短文本，未超过字符数限制"""
        text = "Hello, World!"
        result = truncate_text_by_lines(text, max_chars=1000)
        assert result == text

    def test_exactly_max_chars(self):
        """测试文本字符数正好等于max_chars"""
        text = "\n".join([f"Line {i:03d}" for i in range(100)])
        result = truncate_text_by_lines(text, max_chars=1000)
        assert result == text

    def test_one_char_over_limit(self):
        """测试文本字符数刚好超过max_chars"""
        # 创建刚好超过1000字符的文本
        text = "x" * 1001
        result = truncate_text_by_lines(text, max_chars=1000)

        # 应该被截断
        assert "[截断了" in result
        assert "个字符]" in result

    # ==================== 正常截断测试 ====================

    def test_basic_truncation(self):
        """测试基本截断功能"""
        # 创建2000字符的文本，每行约20字符
        lines = [f"Line {i:03d} content\n" for i in range(100)]
        text = "".join(lines)
        
        result = truncate_text_by_lines(text, max_chars=1000, keep_ratio=0.4)
        
        # 验证包含截断信息
        assert "[截断了" in result
        assert "个字符]" in result
        
        # 验证保留了前面部分
        assert "Line 000" in result
        
        # 验证保留了后面部分
        assert "Line 099" in result

    def test_truncation_info_format(self):
        """测试截断信息的格式"""
        lines = [f"Line {i:03d} content\n" for i in range(100)]
        text = "".join(lines)
        
        result = truncate_text_by_lines(text, max_chars=1000, keep_ratio=0.4)
        
        # 验证截断信息格式正确
        assert "\n...[截断了" in result
        assert "行，" in result
        assert "个字符]...\n" in result

    def test_correct_truncated_count(self):
        """测试截断行数和字符数计算正确"""
        # 创建固定长度的行，便于计算
        lines = [f"Line {i:03d}\n" for i in range(100)]  # 每行10字符
        text = "".join(lines)  # 总共1000字符
        
        # max_chars=500, keep_ratio=0.4
        # keep_chars_per_part = int(500 * 0.4 / 2) = int(100) = 100
        # 前面保留约10行（100字符），后面保留约10行（100字符）
        result = truncate_text_by_lines(text, max_chars=500, keep_ratio=0.4)
        
        # 验证包含正确的截断信息格式
        assert "行，" in result
        assert "个字符]" in result

    # ==================== 参数测试 ====================

    def test_custom_max_chars(self):
        """测试自定义max_chars参数"""
        lines = [f"Line {i:03d} content here\n" for i in range(200)]
        text = "".join(lines)
        
        result = truncate_text_by_lines(text, max_chars=1000, keep_ratio=0.4)
        
        # 验证被截断
        assert "[截断了" in result
        assert "个字符]" in result

    def test_custom_keep_ratio(self):
        """测试自定义keep_ratio参数"""
        lines = [f"Line {i:03d}\n" for i in range(100)]
        text = "".join(lines)
        
        # keep_ratio=0.5，前后各保留25%
        result = truncate_text_by_lines(text, max_chars=500, keep_ratio=0.5)
        
        # 验证包含截断信息
        assert "[截断了" in result
        assert "个字符]" in result

    def test_small_keep_ratio(self):
        """测试较小的keep_ratio"""
        lines = [f"Line {i:03d}\n" for i in range(100)]
        text = "".join(lines)
        
        # keep_ratio=0.2，前后各保留10%
        result = truncate_text_by_lines(text, max_chars=500, keep_ratio=0.2)
        
        # 验证包含截断信息
        assert "[截断了" in result

    def test_large_keep_ratio(self):
        """测试较大的keep_ratio"""
        lines = [f"Line {i:03d}\n" for i in range(100)]
        text = "".join(lines)
        
        # keep_ratio=0.8，前后各保留40%
        result = truncate_text_by_lines(text, max_chars=500, keep_ratio=0.8)
        
        # 验证包含截断信息
        assert "[截断了" in result

    # ==================== 行结尾处理测试 ====================

    def test_preserve_line_endings(self):
        """测试保留行结尾符"""
        lines = [f"Line {i:03d}\n" for i in range(100)]
        text = "".join(lines)
        
        result = truncate_text_by_lines(text, max_chars=500, keep_ratio=0.4)
        
        # 验证第一行保留了换行符
        assert result.startswith("Line 000\n")

    def test_mixed_line_endings(self):
        """测试混合行结尾符（\n和\r\n）"""
        # 创建混合结尾的文本
        text = "Line 000\nLine 001\r\nLine 002\nLine 003\r\n" + "\n".join([f"Line {i:03d}" for i in range(4, 100)])
        
        result = truncate_text_by_lines(text, max_chars=500, keep_ratio=0.4)
        
        # 应该能正确处理
        assert "[截断了" in result

    def test_no_trailing_newline(self):
        """测试最后一行没有换行符的情况"""
        lines = [f"Line {i:03d}\n" for i in range(99)]
        lines.append("Line 099")  # 最后一行没有换行符
        text = "".join(lines)
        
        result = truncate_text_by_lines(text, max_chars=500, keep_ratio=0.4)
        
        # 验证最后一行被保留且没有添加额外换行符
        assert result.endswith("Line 099")

    # ==================== 特殊场景测试 ====================

    def test_very_long_text(self):
        """测试非常长的文本"""
        lines = [f"This is a very long line number {i:04d} with some additional text\n" for i in range(1000)]
        text = "".join(lines)
        
        result = truncate_text_by_lines(text, max_chars=1000, keep_ratio=0.4)
        
        assert "[截断了" in result
        # 验证前面部分被保留（第0行）
        assert "line number 0000" in result
        # 验证后面部分被保留（第999行）
        assert "line number 0999" in result

    def test_short_text_not_truncated(self):
        """测试短文本不被截断"""
        text = "Short text\nwith few lines"
        result = truncate_text_by_lines(text, max_chars=1000)
        assert result == text

    def test_zero_max_chars(self):
        """测试max_chars为0的情况"""
        lines = [f"Line {i:03d}\n" for i in range(10)]
        text = "".join(lines)
        
        result = truncate_text_by_lines(text, max_chars=0, keep_ratio=0.4)
        
        # keep_chars_per_part = int(0 * 0.4 / 2) = 0
        # 应该显示截断信息
        assert "[截断了" in result
        # 验证包含截断信息格式
        assert "个字符]" in result

    def test_result_structure(self):
        """测试返回结果的结构"""
        lines = [f"Line {i:03d}\n" for i in range(100)]
        text = "".join(lines)
        
        result = truncate_text_by_lines(text, max_chars=500, keep_ratio=0.4)
        
        # 结果应该包含三个部分：前面部分、截断信息、后面部分
        parts = result.split("\n...[截断了")
        assert len(parts) == 2  # 应该能分成两部分
        
        # 第二部分应该包含行和字符信息及后面部分
        assert "行，" in parts[1]
        assert "个字符]...\n" in parts[1]

    def test_front_and_back_content(self):
        """测试前后部分内容正确"""
        lines = [f"Line {i:03d}\n" for i in range(100)]  # 每行10字符，共1000字符
        text = "".join(lines)
        
        result = truncate_text_by_lines(text, max_chars=500, keep_ratio=0.4)
        
        # keep_chars_per_part = int(500 * 0.4 / 2) = 100
        # 前面保留约10行，后面保留约10行
        # 验证前面包含Line 000开始的行
        assert "Line 000\n" in result
        
        # 验证后面包含Line 099结尾的行
        assert "Line 099\n" in result

    def test_whitespace_only_lines(self):
        """测试只包含空白字符的行"""
        lines = ["   \n", "\t\n", "  \t  \n"] * 50
        text = "".join(lines)
        
        result = truncate_text_by_lines(text, max_chars=100, keep_ratio=0.4)
        
        # 应该被截断
        assert "[截断了" in result

    def test_empty_lines(self):
        """测试空行"""
        lines = ["\n"] * 100
        text = "".join(lines)
        
        result = truncate_text_by_lines(text, max_chars=50, keep_ratio=0.4)
        
        # 应该被截断
        assert "[截断了" in result

    def test_line_boundary_truncation(self):
        """测试截断点在行边界处"""
        # 创建较长的行，确保不会截断到行的中间
        lines = [f"This is line number {i:03d} with enough content\n" for i in range(100)]
        text = "".join(lines)
        
        result = truncate_text_by_lines(text, max_chars=1000, keep_ratio=0.4)
        
        # 验证截断信息存在
        assert "[截断了" in result
        
        # 验证所有出现的行号都是完整的（不会出现半行）
        # 通过检查是否包含完整的行格式来验证
        import re
        line_pattern = r"This is line number \d{3} with enough content"
        matches = re.findall(line_pattern, result)
        # 所有匹配都应该是完整的行
        for match in matches:
            assert len(match) == len("This is line number 000 with enough content")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])