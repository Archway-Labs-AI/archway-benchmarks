from archway_benchmarks.cli import main


def test_runs_command_on_empty_db(tmp_path, capsys):
    db = tmp_path / "empty.db"
    assert main(["runs", "--db", str(db)]) == 0
    out = capsys.readouterr().out
    assert "no runs" in out


def test_no_subcommand_prints_help(capsys):
    assert main([]) == 0
    out = capsys.readouterr().out
    assert "archway-bench" in out
