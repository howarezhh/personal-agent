from backend.main import app


def test_openapi_includes_unified_error_and_sse_contracts():
    schema = app.openapi()
    schemas = schema.get("components", {}).get("schemas", {})

    assert "ErrorResponse" in schemas
    assert "SSEEvent" in schemas
    assert "SuccessResponse_AskResponse_" in schemas

    ask_operation = schema["paths"]["/api/v1/chat/ask"]["post"]
    assert ask_operation["x-sse-event-schema"] == {"$ref": "#/components/schemas/SSEEvent"}
    assert "application/json" in ask_operation["responses"]["200"]["content"]
    assert "text/event-stream" in ask_operation["responses"]["200"]["content"]
