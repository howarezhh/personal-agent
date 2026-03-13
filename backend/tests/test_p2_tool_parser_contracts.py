from backend.file_processors.parsers.excel_text_parser import TextParser
from backend.tools.calculator.calculator_tool import CalculatorTool


def test_base_tool_exposes_standard_contract_surface():
    tool = CalculatorTool()
    assert tool.name == tool.get_name()
    assert isinstance(tool.input_schema, dict)
    assert isinstance(tool.output_schema, dict)
    assert isinstance(tool.timeout, int)


def test_base_parser_exposes_supported_types_alias():
    parser = TextParser()
    assert parser.supported_types() == parser.get_supported_extensions()

