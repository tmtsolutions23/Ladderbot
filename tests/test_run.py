"""Tests for CLI entry point."""
import pytest

from ladderbot.run import build_parser


class TestBuildParser:
    def test_default_args(self):
        parser = build_parser()
        args = parser.parse_args([])
        assert args.picks is False
        assert args.dashboard is False
        assert args.status is False
        assert args.backtest is False
        assert args.refresh is False
        assert args.sport is None
        assert args.web is False
        assert args.port == 8000

    def test_picks_flag(self):
        parser = build_parser()
        args = parser.parse_args(["--picks"])
        assert args.picks is True

    def test_dashboard_flag(self):
        parser = build_parser()
        args = parser.parse_args(["--dashboard"])
        assert args.dashboard is True

    def test_status_flag(self):
        parser = build_parser()
        args = parser.parse_args(["--status"])
        assert args.status is True

    def test_backtest_flag(self):
        parser = build_parser()
        args = parser.parse_args(["--backtest"])
        assert args.backtest is True

    def test_refresh_flag(self):
        parser = build_parser()
        args = parser.parse_args(["--refresh"])
        assert args.refresh is True

    def test_sport_nba(self):
        parser = build_parser()
        args = parser.parse_args(["--sport", "nba"])
        assert args.sport == "nba"

    def test_sport_nhl(self):
        parser = build_parser()
        args = parser.parse_args(["--sport", "nhl"])
        assert args.sport == "nhl"

    def test_sport_invalid(self):
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["--sport", "mlb"])

    def test_web_flag(self):
        parser = build_parser()
        args = parser.parse_args(["--web"])
        assert args.web is True

    def test_custom_port(self):
        parser = build_parser()
        args = parser.parse_args(["--web", "--port", "8080"])
        assert args.web is True
        assert args.port == 8080

    def test_combined_flags(self):
        parser = build_parser()
        args = parser.parse_args(["--picks", "--sport", "nba", "--refresh"])
        assert args.picks is True
        assert args.sport == "nba"
        assert args.refresh is True

    def test_config_path(self):
        parser = build_parser()
        args = parser.parse_args(["--config", "/tmp/my_config.yaml"])
        assert args.config == "/tmp/my_config.yaml"
