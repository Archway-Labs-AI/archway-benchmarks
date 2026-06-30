import json
import urllib.parse
from pathlib import Path

import pytest

from archway_benchmarks.engines.archway import (
    ArchwayAnalysisEngine,
    ArchwayAnalysisResult,
    ArchwayTranslation,
)


def test_archway_analysis_engine_passes_body_summary_policy(monkeypatch, tmp_path):
    main = tmp_path / "main.py"
    main.write_text("x = 1\n", encoding="utf-8")
    seen = {}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return json.dumps({"module": {"bindings": {}}, "functions": []}).encode()

    def fake_urlopen(req, timeout):
        seen["url"] = req.full_url
        seen["timeout"] = timeout
        return _Resp()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    result = ArchwayAnalysisEngine(
        server_url="http://archway.test:8788",
        timeout=7,
        body_summary_consumption="safe",
    ).analyze(ArchwayTranslation(source="x = 1\n", path=str(main)))

    assert isinstance(result, ArchwayAnalysisResult)
    assert seen["timeout"] == 7
    query = urllib.parse.parse_qs(urllib.parse.urlparse(seen["url"]).query)
    assert query["module"] == ["main.py"]
    assert query["root"] == [str(tmp_path)]
    assert query["body_summary_consumption"] == ["safe"]


def test_archway_analysis_engine_rejects_unknown_body_summary_policy():
    with pytest.raises(ValueError, match="body_summary_consumption"):
        ArchwayAnalysisEngine(body_summary_consumption="aggressive")
