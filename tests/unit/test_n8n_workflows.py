from scripts.validate_n8n_workflows import EXPECTED_WORKFLOWS, load_workflows, validate_all


def test_n8n_workflows_are_present_and_valid() -> None:
    workflows = load_workflows()
    assert {workflow["name"] for workflow in workflows} == EXPECTED_WORKFLOWS
    assert validate_all() == []
