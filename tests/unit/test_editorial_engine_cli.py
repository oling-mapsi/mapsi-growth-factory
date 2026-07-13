from app.cli import build_parser


def test_generate_campaign_parser_supports_real_mode() -> None:
    args = build_parser().parse_args(["generate-campaign", "--mode", "real", "--dry-run"])

    assert args.command == "generate-campaign"
    assert args.mode == "real"
    assert args.dry_run is True
