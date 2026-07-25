import json

from app import cli


def test_knowledge_validate_parser_is_available() -> None:
    args = cli.build_parser().parse_args(["knowledge:validate"])

    assert args.command == "knowledge:validate"


def test_mapsi_site_diagnose_parser_is_available() -> None:
    args = cli.build_parser().parse_args(["mapsi-site:diagnose", "--skip-preview-probe"])

    assert args.command == "mapsi-site:diagnose"
    assert args.skip_preview_probe is True


def test_cli_mapsi_site_diagnose_outputs_report(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        cli.argparse.ArgumentParser,
        "parse_args",
        lambda self: type("Args", (), {"command": "mapsi-site:diagnose", "skip_preview_probe": False})(),
    )
    monkeypatch.setattr(
        cli,
        "_mapsi_site_diagnose",
        lambda **kwargs: {
            "target_url": "https://mapsi.fr",
            "configuration": {"configured": True},
            "authentication": {"ok": True},
            "health": {"ok": True},
            "contract": {"version": "1.0.0"},
            "preview_probe": {"executed": True},
        },
    )

    assert cli.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["target_url"] == "https://mapsi.fr"
    assert payload["contract"]["version"] == "1.0.0"
