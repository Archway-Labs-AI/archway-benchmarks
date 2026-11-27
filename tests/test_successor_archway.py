from dataclasses import replace

from archway_benchmarks.benchmarks.typeevalpy import TypeEvalPyBenchmark
from archway_benchmarks.engines.archway import ArchwayTranslationEngine
from archway_benchmarks.engines.successor_archway import (
    ROOT_POLICY_CALLABLE_BODIES,
    ROOT_POLICY_ENTRY,
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


def _predict(snippet, translator=None):
    result = SuccessorArchwayAnalysisEngine().analyze(
        (translator or ArchwayTranslationEngine()).translate(
            snippet.source, snippet.file_path
        )
    )
    return result, SuccessorTypeEvalPyAdapter().to_annotations(result, snippet)


def _by_location(annotations):
    return {item.location: item.types for item in annotations}


def test_predictions_do_not_depend_on_the_answer_key(tmp_path):
    """The adapter reads the snippet's annotations only to report gaps."""

    snippet = _snippet(
        tmp_path,
        "import os\n"
        "class Box:\n"
        "    size = 1\n"
        "    def __init__(self, content):\n"
        "        self.content = content\n"
        "    def get(self):\n"
        "        return self.content\n"
        "def unused():\n"
        "    return 2.5\n"
        "f = lambda y: y\n"
        "d = {'a': [1, 'b']}\n"
        "box = Box(f(2))\n"
        "value = box.get()\n",
        """[
          {"file":"main.py","line_number":3,"col_offset":5,"variable":"Box.size","type":["int"]},
          {"file":"main.py","line_number":6,"col_offset":9,"function":"Box.get","type":["int"]},
          {"file":"main.py","line_number":8,"col_offset":5,"function":"unused","type":["float"]},
          {"file":"main.py","line_number":13,"col_offset":1,"variable":"value","type":["int"]},
          {"file":"main.py","line_number":13,"col_offset":1,"variable":"wrong","type":["str"]}
        ]""",
    )
    blind = replace(snippet, annotations=())

    keyed_result, keyed = _predict(snippet)
    blind_result, unkeyed = _predict(blind)

    assert keyed == unkeyed
    assert _by_location(keyed) == {
        location: item.types
        for location, item in blind_result.projection.items()
        if item.types
    }
    # Every answer the engine has is predicted at its own location; the
    # answer key's invented location stays a reported gap, not a prediction.
    assert set(snippet.annotations[:4]) <= set(keyed)
    assert [gap.classification for gap in keyed_result.gaps].count(
        "provenance_unmapped"
    ) == 1
    assert all(
        gap.classification == "unexpected_prediction"
        for gap in blind_result.gaps
    )
    # Engine observations that TypeEvalPy does not annotate are not
    # projected: import and class bindings, the method receiver, the
    # ``__init__`` return, and use-site reads.
    names = {(item.location.kind, item.location.name) for item in keyed}
    assert not names & {
        ("variable", "os"), ("variable", "Box"), ("parameter", "self"),
        ("return", "Box.__init__"), ("variable", "unused"),
    }
    assert ("variable", "d['a'][1]") in names


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
    assert _by_location(predictions) == _by_location(snippet.annotations)
    assert result.gaps == []
    assert result.forward is not None
    assert result.forward.cache_hits == 0
    assert len(result.forward.roots) == 1


def test_successor_frontend_closes_explicit_dependency_roots(tmp_path):
    snippet = _snippet(
        tmp_path,
        "from library import produce\nresult = produce()\n",
        """[
          {"file":"main.py","line_number":2,"col_offset":1,"variable":"result","type":["Nonetype"]}
        ]""",
    )
    dependencies = tmp_path / "dependencies"
    dependencies.mkdir()
    (dependencies / "library.py").write_text(
        "def produce():\n    return None\n"
    )
    translation = ArchwayTranslationEngine(
        corpus_root=tmp_path,
        dependency_roots=(dependencies,),
    ).translate(snippet.source, snippet.file_path)

    result = SuccessorArchwayAnalysisEngine().analyze(translation)
    predictions = SuccessorTypeEvalPyAdapter().to_annotations(result, snippet)

    assert result.error is None
    # The import binding is not a TypeEvalPy entity; the call result is.
    assert _by_location(predictions) == _by_location(snippet.annotations)
    assert result.gaps == []


def test_successor_loader_supplies_root_and_dependency_filenames(tmp_path):
    snippet = _snippet(
        tmp_path,
        "from library import path\nfilename = __file__\nresult = path\n",
        '[{"file":"main.py","line_number":2,"col_offset":1,"variable":"filename","type":["str"]},'
        '{"file":"main.py","line_number":3,"col_offset":1,"variable":"result","type":["str"]}]',
    )
    dependencies = tmp_path / "dependencies"
    dependencies.mkdir()
    (dependencies / "library.py").write_text("path = __file__\n")
    translation = ArchwayTranslationEngine(dependency_roots=(dependencies,)).translate(snippet.source, snippet.file_path)
    result = SuccessorArchwayAnalysisEngine().analyze(translation)
    assert result.error is None
    predictions = SuccessorTypeEvalPyAdapter().to_annotations(result, snippet)
    assert _by_location(predictions) == _by_location(snippet.annotations)


def test_successor_adapter_reads_contextual_return_observation_without_fallback(
    tmp_path,
):
    snippet = _snippet(
        tmp_path,
        "def identity(value):\n    return value\nanswer = identity(3)\n",
        """[
          {"file":"main.py","line_number":1,"col_offset":5,"function":"identity","type":["int"]},
          {"file":"main.py","line_number":1,"col_offset":14,"parameter":"value","function":"identity","type":["int"]},
          {"file":"main.py","line_number":3,"col_offset":1,"variable":"answer","type":["int"]}
        ]""",
    )
    result, predictions = _predict(snippet)

    assert _by_location(predictions) == _by_location(snippet.annotations)
    assert result.gaps == []


def test_successor_public_workload_refines_uninvoked_returns_in_one_session(
    tmp_path,
):
    snippet = _snippet(
        tmp_path,
        "def first(value):\n"
        "    return True\n"
        "def second():\n"
        "    return 1.5\n",
        """[
          {"file":"main.py","line_number":1,"col_offset":5,"function":"first","type":["bool"]},
          {"file":"main.py","line_number":3,"col_offset":5,"function":"second","type":["float"]}
        ]""",
    )
    result = SuccessorArchwayAnalysisEngine(
        root_policy=ROOT_POLICY_ENTRY
    ).analyze(
        ArchwayTranslationEngine().translate(snippet.source, snippet.file_path)
    )

    predictions = SuccessorTypeEvalPyAdapter().to_annotations(result, snippet)

    assert _by_location(predictions) == _by_location(snippet.annotations)
    assert result.gaps == []
    assert result.root_policy == ROOT_POLICY_ENTRY
    assert result.callable_bodies is None
    # With the entry-only root policy the workload seeds only the module.
    # Every open catalogued observation (not the answer key's locations) is
    # then demanded in one shared wave, which reaches both uninvoked bodies.
    assert len(result.forward.roots) == 1
    assert result.forward.knowledge_deltas
    assert result.demand_waves == 1
    assert len(result.targeted_runs) == 1
    assert len(result.targeted_runs[0].roots) >= 2


def test_successor_default_root_policy_roots_every_callable_body(tmp_path):
    """Uncalled functions are analysed because every body is a root."""

    snippet = _snippet(
        tmp_path,
        "def first(value):\n"
        "    return True\n"
        "def second():\n"
        "    return 1.5\n",
        "[]",
    )
    result = SuccessorArchwayAnalysisEngine().analyze(
        ArchwayTranslationEngine().translate(snippet.source, snippet.file_path)
    )

    assert result.root_policy == ROOT_POLICY_CALLABLE_BODIES
    assert result.callable_bodies is not None
    assert len(result.callable_bodies.roots) == 3  # module + two bodies
    # Before any adapter demand, both uninvoked returns already resolved.
    resolved = {
        item.name: result.session.store.resolved(item.address)
        for item in result.session.type_observations()
        if item.kind == "return"
    }
    assert {name for name, fact in resolved.items() if fact and fact.value} == {
        "first", "second"
    }
    predictions = SuccessorTypeEvalPyAdapter().to_annotations(result, snippet)
    assert {
        (item.location.name, frozenset(item.types)) for item in predictions
        if item.location.kind == "return"
    } == {("first", frozenset({"bool"})), ("second", frozenset({"float"}))}


def test_successor_adapter_remaps_contexts_discovered_by_refinement(tmp_path):
    snippet = _snippet(
        tmp_path,
        "# nested receiver contexts\n"
        "class Value:\n"
        "    def result(self):\n"
        "        return 13\n"
        "\n\n"
        "class Wrapper:\n"
        "    def __init__(self, value):\n"
        "        self.value = value\n"
        "\n"
        "    def result(self):\n"
        "        return self.value.result()\n"
        "\n\n"
        "class Outer:\n"
        "    def __init__(self):\n"
        "        self.value = Value()\n"
        "\n"
        "    def result(self):\n"
        "        wrapper = Wrapper(self.value)\n"
        "        return wrapper.result()\n"
        "\n\n"
        "outer = Outer()\n"
        "answer = outer.result()\n",
        """[
          {"file":"main.py","line_number":11,"col_offset":9,"function":"Wrapper.result","type":["int"]},
          {"file":"main.py","line_number":19,"col_offset":9,"function":"Outer.result","type":["int"]},
          {"file":"main.py","line_number":25,"col_offset":1,"variable":"answer","type":["int"]}
        ]""",
    )
    result = SuccessorArchwayAnalysisEngine().analyze(
        ArchwayTranslationEngine().translate(snippet.source, snippet.file_path)
    )

    predictions = SuccessorTypeEvalPyAdapter().to_annotations(result, snippet)

    assert snippet.annotations[0] in predictions
    assert not any(
        gap.location == snippet.annotations[0].location
        for gap in result.gaps
    )


def test_successor_adapter_maps_qualified_class_attribute_observations(
    tmp_path,
):
    snippet = _snippet(
        tmp_path,
        "class MyClass:\n"
        "    class_var = 1.5\n"
        "    def __init__(self, values):\n"
        "        self.values = values\n"
        "item = MyClass([1, 2])\n",
        """[
          {"file":"main.py","line_number":2,"col_offset":5,"variable":"MyClass.class_var","type":["float"]},
          {"file":"main.py","line_number":3,"col_offset":24,"parameter":"values","function":"MyClass.__init__","type":["list"]},
          {"file":"main.py","line_number":4,"col_offset":9,"variable":"self.values","function":"MyClass.__init__","type":["list"]},
          {"file":"main.py","line_number":4,"col_offset":9,"variable":"self.values[0]","function":"MyClass.__init__","type":["int"]},
          {"file":"main.py","line_number":4,"col_offset":9,"variable":"self.values[1]","function":"MyClass.__init__","type":["int"]},
          {"file":"main.py","line_number":5,"col_offset":1,"variable":"item","type":["MyClass"]}
        ]""",
    )
    result, predictions = _predict(snippet)

    # Instance attributes keep the engine's receiver spelling and qualified
    # method scope (TypeEvalPy micro's convention); the adapter does not
    # respell them to an answer key's ``Owner.attr`` or bare method name.
    assert _by_location(predictions) == _by_location(snippet.annotations)
    assert result.gaps == []


def test_successor_adapter_scopes_instance_attribute_to_qualified_method(tmp_path):
    snippet = _snippet(
        tmp_path,
        "class Outer:\n"
        "    class Inner:\n"
        "        def __init__(self):\n"
        "            self.values = [1, 2]\n"
        "item = Outer.Inner()\n",
        """[
          {"file":"main.py","line_number":4,"col_offset":13,"variable":"self.values","function":"Outer.Inner.__init__","type":["list"]},
          {"file":"main.py","line_number":4,"col_offset":13,"variable":"self.values[0]","function":"Outer.Inner.__init__","type":["int"]},
          {"file":"main.py","line_number":4,"col_offset":13,"variable":"self.values[1]","function":"Outer.Inner.__init__","type":["int"]},
          {"file":"main.py","line_number":5,"col_offset":1,"variable":"item","type":["Outer.Inner"]}
        ]""",
    )
    result, predictions = _predict(snippet)

    assert _by_location(predictions) == _by_location(snippet.annotations)
    assert result.gaps == []


def test_successor_adapter_names_method_return_by_qualified_name(tmp_path):
    snippet = _snippet(
        tmp_path,
        "class Worker:\n"
        "    def run(self):\n"
        "        return 3\n"
        "result = Worker().run()\n",
        """[
          {"file":"main.py","line_number":2,"col_offset":9,"function":"Worker.run","type":["int"]},
          {"file":"main.py","line_number":4,"col_offset":1,"variable":"result","type":["int"]}
        ]""",
    )
    result, predictions = _predict(snippet)

    # The receiver ``self`` is not a TypeEvalPy parameter.
    assert _by_location(predictions) == _by_location(snippet.annotations)
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
    assert _by_location(predictions) == _by_location(snippet.annotations)
    assert result.gaps == []


def test_successor_adapter_projects_no_index_from_a_summary_slot(tmp_path):
    snippet = _snippet(
        tmp_path,
        "def generate():\n"
        "    yield 1\n"
        "values = generate()\n",
        """[
          {"file":"main.py","line_number":1,"col_offset":5,"function":"generate","type":["generator"]},
          {"file":"main.py","line_number":3,"col_offset":1,"variable":"values","type":["generator"]},
          {"file":"main.py","line_number":3,"col_offset":1,"variable":"values[0]","type":["int"]}
        ]""",
    )
    result, predictions = _predict(snippet)

    # The engine reports only the generator's element summary; choosing the
    # index ``0`` would need the answer key, so it stays a reported gap.
    assert _by_location(predictions) == _by_location(snippet.annotations[:2])
    assert [(gap.classification, gap.location.name) for gap in result.gaps] == [
        ("provenance_unmapped", "values[0]")
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
    assert audit.family_groups == {
        "provenance_unmapped|assignments/forward|return": 1
    }
    assert audit.forward_events > 0
    # Knowledge commits remain available as cost telemetry. Their count is an
    # implementation detail of the scheduler topology, not a benchmark law.
    assert audit.knowledge_deltas > 0
    assert audit.resolved_facts > 1


def test_gap_audit_can_disable_detailed_scheduler_events(tmp_path):
    _snippet(
        tmp_path,
        "x = 1\n",
        """[
          {"file":"main.py","line_number":1,"col_offset":1,"variable":"x","type":["int"]}
        ]""",
    )

    progress = []
    audit = audit_successor_typeevalpy(
        TypeEvalPyBenchmark(tmp_path),
        record_events=False,
        suite_prefixes=("assignments/for",),
        progress=lambda completed, total: progress.append((completed, total)),
    )

    assert audit.exact == 1
    assert audit.forward_events == 0
    assert audit.knowledge_deltas > 0
    assert audit.resolved_facts > 1
    assert progress == [(1, 1)]


def test_gap_audit_reports_public_targeted_refinement(tmp_path):
    _snippet(
        tmp_path,
        "def untouched(value):\n"
        "    return 3\n",
        """[
          {"file":"main.py","line_number":1,"col_offset":5,"function":"untouched","type":["int"]}
        ]""",
    )

    audit = audit_successor_typeevalpy(
        TypeEvalPyBenchmark(tmp_path),
        record_events=False,
        root_policy=ROOT_POLICY_ENTRY,
    )

    assert audit.exact == 1
    assert audit.targeted_roots >= 1
    assert audit.targeted_events == 0
    assert audit.targeted_knowledge_deltas > 0
    assert audit.targeted_topology_changes > 0


def test_successor_adapter_uses_route_feasibility_for_precise_answer(tmp_path):
    snippet = _snippet(
        tmp_path,
        "def choose(flag):\n"
        "    if flag:\n"
        "        return 1\n"
        '    return "no"\n'
        "result = choose(True)\n",
        """[
          {"file":"main.py","line_number":1,"col_offset":5,"function":"choose","type":["int"]},
          {"file":"main.py","line_number":1,"col_offset":12,"parameter":"flag","function":"choose","type":["bool"]},
          {"file":"main.py","line_number":5,"col_offset":1,"variable":"result","type":["int"]}
        ]""",
    )
    result, predictions = _predict(snippet)

    assert _by_location(predictions) == _by_location(snippet.annotations)
    assert result.gaps == []
