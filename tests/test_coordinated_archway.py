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
