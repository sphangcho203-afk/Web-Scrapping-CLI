from internet_hands.openapi import _guess_capability, _load_document, _parameter_summary


def test_load_openapi_yaml():
    spec = _load_document(
        """
openapi: 3.0.3
info:
  title: Example
  version: '1'
paths:
  /users/{id}:
    get:
      operationId: getUser
"""
    )
    assert spec["openapi"] == "3.0.3"
    assert spec["info"]["title"] == "Example"


def test_capability_inference():
    assert _guess_capability("/videos/{id}", ["Media"]) == "video"
    assert _guess_capability("/accounts/{id}", ["Users"]) == "profile"
    assert _guess_capability("/search", ["Discovery"]) == "search"


def test_parameter_merge_deduplicates():
    path_item = {
        "parameters": [
            {"name": "id", "in": "path", "required": True},
        ]
    }
    operation = {
        "parameters": [
            {"name": "id", "in": "path", "required": True},
            {"name": "fields", "in": "query", "required": False},
        ]
    }
    params = _parameter_summary(operation, path_item)
    assert params == [
        {"name": "id", "in": "path", "required": True, "description": None},
        {"name": "fields", "in": "query", "required": False, "description": None},
    ]
