"""research 模块单元测试。"""

from types import SimpleNamespace

from trading_agent import research


def _scan_result(ticker: str, gate_pass: bool = True, **overrides) -> dict:
    base = {
        "status": "success",
        "ticker": ticker,
        "gate_pass": gate_pass,
        "gate_reason": "gate ok" if gate_pass else "gate fail",
        "group": "stock",
        "close": 100.0,
        "change_pct": 1.0,
    }
    base.update(overrides)
    return base


def _analysis_report(
    ticker: str,
    *,
    action: str = "enter",
    entry_allowed: bool = True,
    logic_score: int = 70,
    logic_trend: str = "stable",
    stage: str = "mid",
    continuation: str = "strong",
    ideal_entry: bool = True,
    position_multiplier: float = 1.0,
) -> dict:
    return {
        "status": "success",
        "ticker": ticker,
        "decision_report": {
            "action": action,
            "entry_allowed": entry_allowed,
            "position_multiplier": position_multiplier,
        },
        "logic_report": {
            "logic": {
                "score": logic_score,
                "trend": logic_trend,
            }
        },
        "trend_report": {
            "fish_body": {
                "stage": stage,
                "ideal_entry": ideal_entry,
            },
            "continuation": {
                "verdict": continuation,
            },
        },
    }


def test_build_research_report_only_analyzes_gate_pass_candidates(monkeypatch):
    calls: list[str] = []

    def fake_build_analysis_report(ticker, **kwargs):
        calls.append(ticker)
        return _analysis_report(ticker)

    monkeypatch.setattr(
        research,
        "scanner",
        SimpleNamespace(
            resolve_tickers=lambda tickers_csv, group: ["AAPL", "MSFT", "TSLA"],
            scan_batch=lambda tickers, delay, with_fund: [
                _scan_result("AAPL", gate_pass=True),
                _scan_result("MSFT", gate_pass=False),
                _scan_result("TSLA", gate_pass=True),
            ],
        ),
    )
    monkeypatch.setattr(
        research,
        "analyzer",
        SimpleNamespace(build_analysis_report=fake_build_analysis_report),
    )

    report = research.build_research_report(tickers=["AAPL", "MSFT", "TSLA"], save_history=False)

    assert calls == ["AAPL", "TSLA"]
    assert report["summary"]["gate_pass"] == 2
    assert [item["ticker"] for item in report["analyses"]] == ["AAPL", "TSLA"]


def test_build_research_report_applies_limit_after_ranking(monkeypatch):
    reports = {
        "AAA": _analysis_report(
            "AAA",
            action="enter",
            entry_allowed=True,
            logic_score=72,
            logic_trend="stable",
            stage="mid",
            continuation="strong",
            ideal_entry=True,
            position_multiplier=1.0,
        ),
        "BBB": _analysis_report(
            "BBB",
            action="enter",
            entry_allowed=True,
            logic_score=65,
            logic_trend="strengthening",
            stage="early",
            continuation="strong",
            ideal_entry=True,
            position_multiplier=1.5,
        ),
        "CCC": _analysis_report(
            "CCC",
            action="watch",
            entry_allowed=False,
            logic_score=99,
            logic_trend="strengthening",
            stage="early",
            continuation="strong",
            ideal_entry=True,
            position_multiplier=0,
        ),
    }
    monkeypatch.setattr(
        research,
        "scanner",
        SimpleNamespace(
            resolve_tickers=lambda tickers_csv, group: ["AAA", "BBB", "CCC"],
            scan_batch=lambda tickers, delay, with_fund: [
                _scan_result("AAA"),
                _scan_result("BBB"),
                _scan_result("CCC"),
            ],
        ),
    )
    monkeypatch.setattr(
        research,
        "analyzer",
        SimpleNamespace(build_analysis_report=lambda ticker, **kwargs: reports[ticker]),
    )

    report = research.build_research_report(limit=2, save_history=False)

    assert report["summary"]["analyzed"] == 3
    assert report["summary"]["returned"] == 2
    assert [item["ticker"] for item in report["candidates"]] == ["AAA", "BBB"]
    assert [item["rank"] for item in report["candidates"]] == [1, 2]


def test_build_research_report_sorts_by_research_priority(monkeypatch):
    reports = {
        "SLOW": _analysis_report(
            "SLOW",
            action="enter",
            entry_allowed=True,
            logic_score=80,
            logic_trend="stable",
            stage="mid",
            continuation="strong",
            ideal_entry=False,
            position_multiplier=0.8,
        ),
        "BEST": _analysis_report(
            "BEST",
            action="enter",
            entry_allowed=True,
            logic_score=80,
            logic_trend="strengthening",
            stage="early",
            continuation="strong",
            ideal_entry=True,
            position_multiplier=1.2,
        ),
        "WATCH": _analysis_report(
            "WATCH",
            action="watch",
            entry_allowed=False,
            logic_score=95,
            logic_trend="strengthening",
            stage="early",
            continuation="strong",
            ideal_entry=True,
            position_multiplier=0,
        ),
    }
    monkeypatch.setattr(
        research,
        "scanner",
        SimpleNamespace(
            resolve_tickers=lambda tickers_csv, group: ["SLOW", "BEST", "WATCH"],
            scan_batch=lambda tickers, delay, with_fund: [
                _scan_result("SLOW"),
                _scan_result("BEST"),
                _scan_result("WATCH"),
            ],
        ),
    )
    monkeypatch.setattr(
        research,
        "analyzer",
        SimpleNamespace(build_analysis_report=lambda ticker, **kwargs: reports[ticker]),
    )

    report = research.build_research_report(limit=3, save_history=False)

    assert [item["ticker"] for item in report["candidates"]] == ["BEST", "SLOW", "WATCH"]


def test_build_research_report_keeps_scan_and_analysis_errors(monkeypatch):
    def fake_build_analysis_report(ticker, **kwargs):
        if ticker == "FAIL":
            raise RuntimeError("analysis exploded")
        return _analysis_report("OK")

    monkeypatch.setattr(
        research,
        "scanner",
        SimpleNamespace(
            resolve_tickers=lambda tickers_csv, group: ["BAD", "FAIL", "OK"],
            scan_batch=lambda tickers, delay, with_fund: [
                {"status": "error", "ticker": "BAD", "message": "scan exploded"},
                _scan_result("FAIL"),
                _scan_result("OK"),
            ],
        ),
    )
    monkeypatch.setattr(
        research,
        "analyzer",
        SimpleNamespace(build_analysis_report=fake_build_analysis_report),
    )

    report = research.build_research_report(limit=3, save_history=False)

    assert report["summary"]["errors"] == 2
    assert [error["ticker"] for error in report["errors"]] == ["BAD", "FAIL"]
    assert [error["stage"] for error in report["errors"]] == ["scan", "analysis"]
    assert [item["ticker"] for item in report["candidates"]] == ["OK"]


def test_format_research_markdown_includes_rankings():
    report = {
        "generated_at": "2026-04-26T12:00:00+00:00",
        "summary": {
            "group": "mega_cap",
            "scanned": 3,
            "gate_pass": 2,
            "analyzed": 2,
            "returned": 2,
        },
        "candidates": [
            {
                "rank": 1,
                "ticker": "NVDA",
                "action": "enter",
                "logic_score": 88,
                "logic_trend": "strengthening",
                "stage": "early",
                "continuation": "strong",
                "ideal_entry": True,
                "position_multiplier": 1.5,
            },
            {
                "rank": 2,
                "ticker": "MSFT",
                "action": "small_enter",
                "logic_score": 71,
                "logic_trend": "stable",
                "stage": "mid",
                "continuation": "strong",
                "ideal_entry": False,
                "position_multiplier": 0.5,
            },
        ],
        "errors": [],
    }

    markdown = research.format_research_markdown(report)

    assert "Ranked Candidates" in markdown
    assert "| 1 | NVDA | enter |" in markdown
    assert "| 2 | MSFT | small_enter |" in markdown
