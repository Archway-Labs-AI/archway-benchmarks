from archway_benchmarks.benchmarks.typeevalpy import TypeEvalPyBenchmark
from archway_benchmarks.engines.archway import ArchwayTranslationEngine
from archway_benchmarks.engines.coordinated_archway import (
    CoordinatedArchwayAnalysisEngine, CoordinatedTypeEvalPyAdapter,
)


def test_coordinated_adapter_infers_lambda_call_without_legacy_product(tmp_path):
    suite = tmp_path / "lambdas" / "call"
    suite.mkdir(parents=True)
    source = "x = lambda x: x + 1\na = x(1)\n"
    (suite / "main.py").write_text(source)
    (suite / "main_gt.json").write_text("""[
      {"file":"main.py","line_number":1,"col_offset":1,"variable":"x","type":["callable"]},
      {"file":"main.py","line_number":1,"col_offset":12,"function":"lambda","parameter":"x","type":["int"]},
      {"file":"main.py","line_number":2,"col_offset":1,"variable":"a","type":["int"]}
    ]""")
    snippet = TypeEvalPyBenchmark(tmp_path).load()[0]
    translated = ArchwayTranslationEngine().translate(
        snippet.source, snippet.file_path
    )
    result = CoordinatedArchwayAnalysisEngine().analyze(translated)
    predictions = CoordinatedTypeEvalPyAdapter().to_annotations(result, snippet)

    assert result.error is None
    assert {item.location: item.types for item in predictions} == {
        item.location: item.types for item in snippet.annotations
    }


def test_parameter_query_demands_each_reachable_invocation_context(tmp_path):
    suite = tmp_path / "lambdas" / "callable_parameter"
    suite.mkdir(parents=True)
    source = (
        "def leaf():\n"
        "    return 1\n"
        "apply = lambda fn: fn()\n"
        "answer = apply(leaf)\n"
    )
    (suite / "main.py").write_text(source)
    (suite / "main_gt.json").write_text("""[
      {"file":"main.py","line_number":1,"col_offset":5,"function":"leaf","type":["int"]},
      {"file":"main.py","line_number":3,"col_offset":1,"variable":"apply","type":["callable"]},
      {"file":"main.py","line_number":3,"col_offset":16,"function":"lambda","parameter":"fn","type":["callable"]},
      {"file":"main.py","line_number":4,"col_offset":1,"variable":"answer","type":["int"]}
    ]""")
    snippet = TypeEvalPyBenchmark(tmp_path).load()[0]
    result = CoordinatedArchwayAnalysisEngine().analyze(
        ArchwayTranslationEngine().translate(snippet.source, snippet.file_path)
    )

    predictions = CoordinatedTypeEvalPyAdapter().to_annotations(result, snippet)

    assert result.error is None
    assert result.diagnostics == []
    assert {item.location: item.types for item in predictions} == {
        item.location: item.types for item in snippet.annotations
    }


def test_local_variable_query_uses_reachable_invocation_context(tmp_path):
    suite = tmp_path / "assignments" / "augmented"
    suite.mkdir(parents=True)
    source = "def twice(value):\n    value *= 2\n    return value\nanswer = twice(3)\n"
    (suite / "main.py").write_text(source)
    (suite / "main_gt.json").write_text("""[
      {"file":"main.py","line_number":2,"col_offset":5,"function":"twice","variable":"value","type":["int"]},
      {"file":"main.py","line_number":3,"col_offset":5,"function":"twice","type":["int"]},
      {"file":"main.py","line_number":4,"col_offset":1,"variable":"answer","type":["int"]}
    ]""")
    snippet = TypeEvalPyBenchmark(tmp_path).load()[0]
    result = CoordinatedArchwayAnalysisEngine().analyze(
        ArchwayTranslationEngine().translate(snippet.source, snippet.file_path)
    )

    predictions = CoordinatedTypeEvalPyAdapter().to_annotations(result, snippet)

    assert result.error is None
    assert {item.location: item.types for item in predictions} == {
        item.location: item.types for item in snippet.annotations
    }
