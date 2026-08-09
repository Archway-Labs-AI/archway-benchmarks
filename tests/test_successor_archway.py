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


def test_successor_adapter_reads_contextual_return_observation_without_fallback(
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

    assert predictions == list(snippet.annotations)
    assert result.gaps == []


def test_successor_program_translation_expands_available_star_imports(tmp_path):
    suite = tmp_path / "imports" / "import_all"
    suite.mkdir(parents=True)
    (suite / "from_module.py").write_text(
        "def func1():\n    return 42\n\n"
        "def func2():\n    return 'hello'\n"
    )
    (suite / "main.py").write_text(
        "from from_module import *\n"
        "a = func1()\n"
        "b = func2()\n"
    )
    (suite / "main_gt.json").write_text("""[
      {"file":"main.py","line_number":2,"col_offset":1,"variable":"a","type":["int"]},
      {"file":"main.py","line_number":3,"col_offset":1,"variable":"b","type":["str"]}
    ]""")
    benchmark = TypeEvalPyBenchmark(tmp_path)
    snippet = benchmark.load()[0]
    translation = ArchwayTranslationEngine(
        corpus_root=benchmark.corpus_root
    ).translate(snippet.source, snippet.file_path)
    result = SuccessorArchwayAnalysisEngine().analyze(translation)

    predictions = SuccessorTypeEvalPyAdapter().to_annotations(result, snippet)

    assert result.error is None
    assert predictions == list(snippet.annotations)
    assert result.gaps == []


def test_successor_adapter_reads_concrete_slot_from_summary_fact(tmp_path):
    snippet = _snippet(
        tmp_path,
        "def generate():\n"
        "    yield 1\n"
        "values = generate()\n",
        """[
          {"file":"main.py","line_number":3,"col_offset":1,"variable":"values[0]","type":["int"]}
        ]""",
    )
    result = SuccessorArchwayAnalysisEngine().analyze(
        ArchwayTranslationEngine().translate(snippet.source, snippet.file_path)
    )

    predictions = SuccessorTypeEvalPyAdapter().to_annotations(result, snippet)

    assert predictions == list(snippet.annotations)
    assert result.gaps == []


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


def test_successor_adapter_retains_sound_imprecise_answer_as_gap(tmp_path):
    snippet = _snippet(
        tmp_path,
        "def choose(flag):\n"
        "    if flag:\n"
        "        return 1\n"
        '    return "no"\n'
        "result = choose(True)\n",
        """[
          {"file":"main.py","line_number":5,"col_offset":1,"variable":"result","type":["int"]}
        ]""",
    )
    result = SuccessorArchwayAnalysisEngine().analyze(
        ArchwayTranslationEngine().translate(snippet.source, snippet.file_path)
    )

    predictions = SuccessorTypeEvalPyAdapter().to_annotations(result, snippet)

    assert predictions[0].types == frozenset(("int", "str"))
    assert [gap.classification for gap in result.gaps] == [
        "mapped_imprecise"
    ]
