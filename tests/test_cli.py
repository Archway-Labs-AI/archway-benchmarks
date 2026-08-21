from archway_benchmarks.benchmarks.typeevalpy import TypeEvalPyBenchmark
from archway_benchmarks.cli import BENCHMARKS, main
from archway_benchmarks.store import connect, get_scores, list_runs


def test_runs_command_on_empty_db(tmp_path, capsys):
    db = tmp_path / "empty.db"
    assert main(["runs", "--db", str(db)]) == 0
    out = capsys.readouterr().out
    assert "no runs" in out


def test_no_subcommand_prints_help(capsys):
    assert main([]) == 0
    out = capsys.readouterr().out
    assert "archway-bench" in out


def test_successor_run_is_persisted_through_public_pipeline(
    tmp_path, monkeypatch, capsys,
):
    case = tmp_path / "assignments" / "literal"
    case.mkdir(parents=True)
    (case / "main.py").write_text("value = 1\n")
    (case / "main_gt.json").write_text(
        '[{"file":"main.py","line_number":1,"col_offset":1,'
        '"variable":"value","type":["int"]}]'
    )
    monkeypatch.setitem(
        BENCHMARKS, "tiny-successor", lambda: TypeEvalPyBenchmark(tmp_path)
    )
    db = tmp_path / "runs.db"

    assert main([
        "run", "--benchmark", "tiny-successor",
        "--engine", "successor", "--db", str(db),
    ]) == 0

    with connect(db) as connection:
        runs = list_runs(connection)
        assert len(runs) == 1
        scores = get_scores(connection, runs[0].id)
    assert scores["all"]["exact_total"] == 1
    assert scores["all"]["total_annotations"] == 1
    assert "exact 1/1" in capsys.readouterr().out
