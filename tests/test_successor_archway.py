from archway_benchmarks.benchmarks.typeevalpy import TypeEvalPyBenchmark
from archway_benchmarks.engines.archway import ArchwayTranslationEngine
from archway_benchmarks.engines.successor_archway import (
    SuccessorArchwayAnalysisEngine,
    SuccessorTypeEvalPyAdapter,
    audit_successor_typeevalpy,
)


def _snippet(tmp_path, source: str, ground_truth: str):
    suite = tmp_path / "assignments" / "forward"
    suite.mkdir(parents=True)
    (suite / "main.py").write_text(source)
    (suite / "main_gt.json").write_text(ground_truth)
    return TypeEvalPyBenchmark(tmp_path).load()[0]


def test_successor_adapter_reads_module_bindings_from_one_forward_run(tmp_path):
    snippet = _snippet(
        tmp_path,
        "x = 1\ny = x\n",
        """[
          {"file":"main.py","line_number":1,"col_offset":1,"variable":"x","type":["int"]},
          {"file":"main.py","line_number":2,"col_offset":1,"variable":"y","type":["int"]}
        ]""",
    )
    translation = ArchwayTranslationEngine().translate(
        snippet.source, snippet.file_path
    )
    result = SuccessorArchwayAnalysisEngine().analyze(translation)

    predictions = SuccessorTypeEvalPyAdapter().to_annotations(result, snippet)

    assert result.error is None
    assert predictions == list(snippet.annotations)
    assert result.gaps == []
    assert result.forward is not None
    assert result.forward.cache_hit is False


def test_successor_adapter_classifies_non_module_observation_without_fallback(
    tmp_path,
):
    snippet = _snippet(
        tmp_path,
        "def identity(value):\n    return value\nanswer = identity(3)\n",
        """[
          {"file":"main.py","line_number":1,"col_offset":5,"function":"identity","type":["int"]}
        ]""",
    )
    result = SuccessorArchwayAnalysisEngine().analyze(
        ArchwayTranslationEngine().translate(snippet.source, snippet.file_path)
    )

    predictions = SuccessorTypeEvalPyAdapter().to_annotations(result, snippet)

    assert predictions == []
    assert [gap.classification for gap in result.gaps] == [
        "provenance_unmapped"
    ]


def test_gap_audit_retains_representatives_and_forward_cost(tmp_path):
    _snippet(
        tmp_path,
        "x = 1\n",
        """[
          {"file":"main.py","line_number":1,"col_offset":1,"variable":"x","type":["int"]},
          {"file":"main.py","line_number":1,"col_offset":5,"function":"missing","type":["int"]}
        ]""",
    )

    audit = audit_successor_typeevalpy(TypeEvalPyBenchmark(tmp_path))

    assert audit.annotations == 2
    assert audit.predictions == 1
    assert audit.exact == 1
    assert audit.classifications == {"provenance_unmapped": 1}
    assert audit.representatives == {
        "provenance_unmapped|assignments|return": "assignments/forward"
    }
    assert audit.forward_events > 0
    assert audit.knowledge_deltas == 1
    assert audit.resolved_facts > 1
