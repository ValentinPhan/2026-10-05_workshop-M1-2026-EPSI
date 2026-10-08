"""Journaux : historique texte du jour (sentinel-*.log) et rétention des fichiers datés."""
import json
import logging
from datetime import date

from app.logger import Logger, TextHandler, _JsonHandler


def read(path):
    return path.read_text(encoding="utf-8")


def test_event_goes_to_json_and_text(tmp_path):
    log = Logger(tmp_path, "dev")
    log.emit("edge.connected", "\x1b[32mConnecté au broker\x1b[0m", node="esp-node-01")
    day = date.today().isoformat()
    record = json.loads(read(tmp_path / f"events-{day}.jsonl"))
    assert record["event"] == "edge.connected" and record["data"] == {"node": "esp-node-01"}
    text = read(tmp_path / f"sentinel-{day}.log")
    assert "INFO     [edge.connected] Connecté au broker" in text and "\x1b" not in text


def test_logging_messages_go_to_text_with_traceback_and_are_not_duplicated(tmp_path):
    log = Logger(tmp_path, "dev")
    handler = TextHandler(log)
    test_logger = logging.getLogger("sentinel-x.test")
    test_logger.addHandler(handler)
    try:
        test_logger.warning("Raspberry Pi perdu")
        try:
            raise RuntimeError("boom")
        except RuntimeError:
            test_logger.exception("erreur capteur")
        log.emit("log.warning", "Raspberry Pi perdu", level="warning")  # recopie JSON d'un message logging
    finally:
        test_logger.removeHandler(handler)
    text = read(tmp_path / f"sentinel-{date.today().isoformat()}.log")
    assert text.count("Raspberry Pi perdu") == 1
    assert "WARNING  [sentinel-x.test] Raspberry Pi perdu" in text
    assert "ERROR    [sentinel-x.test] erreur capteur" in text and "RuntimeError: boom" in text


def test_purge_keeps_recent_days_and_other_files(tmp_path):
    for name in ("events-2026-09-01.jsonl", "sentinel-2026-09-01.log", "events-2026-10-02.jsonl",
                 "sentinel-2026-10-08.log", "notes.txt", "events-pas-une-date.jsonl"):
        (tmp_path / name).write_text("x", encoding="utf-8")
    log = Logger(tmp_path, "dev", keep_days=7)
    removed = log.purge(date(2026, 10, 8))
    assert removed == ["events-2026-09-01.jsonl", "sentinel-2026-09-01.log"]
    left = sorted(p.name for p in tmp_path.iterdir())
    assert left == ["events-2026-10-02.jsonl", "events-pas-une-date.jsonl", "notes.txt", "sentinel-2026-10-08.log"]


def test_keep_days_zero_keeps_everything(tmp_path):
    (tmp_path / "events-2020-01-01.jsonl").write_text("x", encoding="utf-8")
    assert Logger(tmp_path, "dev", keep_days=0).purge(date(2026, 10, 8)) == []
    assert (tmp_path / "events-2020-01-01.jsonl").exists()


def test_write_errors_never_raise(tmp_path):
    blocker = tmp_path / "pas-un-dossier"
    blocker.write_text("x", encoding="utf-8")
    log = Logger(blocker, "dev")  # le « dossier » des journaux est un fichier : écriture impossible
    log.emit("app.start", "démarrage")
    log.write_text("info", "test", "ligne")


def test_console_only_messages_never_reach_files(tmp_path):
    log = Logger(tmp_path, "dev")
    handlers = [TextHandler(log), _JsonHandler(log)]
    test_logger = logging.getLogger("sentinel-x.secret")
    for h in handlers:
        test_logger.addHandler(h)
    try:
        test_logger.warning("mot de passe : s3cret-initial", extra={"console_only": True})
        test_logger.warning("message ordinaire")
    finally:
        for h in handlers:
            test_logger.removeHandler(h)
    files = "".join(read(p) for p in tmp_path.iterdir())
    assert "s3cret-initial" not in files and "message ordinaire" in files
