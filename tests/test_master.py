import shutil
import uuid

import pytest

from brd import core, db, master, paths
from brd.errors import ProjectAlreadyExistsError, ProjectNotFoundError
from brd.models import Project
from tests.factories import PROJECT, make_card, make_document, make_issue


def _brd():
    return db.connect(paths.brd_db_path())


def _card_owner(card_id):
    """(title, project_id) of a card in brd.db, or None."""
    conn = _brd()
    try:
        row = conn.execute(
            "SELECT cards.title, entities.project_id FROM cards "
            "JOIN entities ON entities.id = cards.id WHERE cards.id = ?",
            (card_id,),
        ).fetchone()
    finally:
        conn.close()
    return tuple(row) if row else None


def test_init_project_writes_nothing_into_the_repo(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    repo.mkdir()

    project = master.init_project(repo)

    assert list(repo.iterdir()) == []
    assert project.name == "myrepo"
    assert project.root_path == str(repo)
    db_path = paths.brd_db_path()
    assert db_path.is_file()
    assert str(db_path).startswith(str(tmp_path / "data"))
    conn = _brd()
    try:
        assert db.list_projects(conn) == [project]
    finally:
        conn.close()


LEGACY_ID = "07a7d240-444a-4b71-b585-b5bc7b50fdf3"


def test_init_project_leaves_gitignore_and_old_markers_alone(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    # The original design: a .brd file holding a UUID that keys a central board.
    uuid_repo = tmp_path / "uuid-repo"
    uuid_repo.mkdir()
    gitignore_bytes = b"__pycache__/"  # no trailing newline: the old append added one
    (uuid_repo / ".gitignore").write_bytes(gitignore_bytes)
    (uuid_repo / ".brd").write_text(f"{LEGACY_ID}\n")
    old_projects_dir = tmp_path / "data" / "brd" / "projects"
    old_projects_dir.mkdir(parents=True)
    legacy = db.connect(old_projects_dir / f"{LEGACY_ID}.db")
    db.init_project_schema(legacy, PROJECT)
    make_card(legacy, "c1", title="Old card")
    legacy.close()
    # The in-repo design: a .brd/ directory holding board.db.
    dir_repo = tmp_path / "dir-repo"
    brd_dir = dir_repo / ".brd"
    brd_dir.mkdir(parents=True)
    in_repo = db.connect(brd_dir / "board.db")
    db.init_project_schema(in_repo, PROJECT)
    make_card(in_repo, "c2", title="In-repo card")
    in_repo.close()
    board_bytes = (brd_dir / "board.db").read_bytes()

    master.init_project(uuid_repo)
    master.init_project(dir_repo)

    assert sorted(p.name for p in uuid_repo.iterdir()) == [".brd", ".gitignore"]
    assert (uuid_repo / ".gitignore").read_bytes() == gitignore_bytes
    assert (uuid_repo / ".brd").read_text() == f"{LEGACY_ID}\n"
    assert [p.name for p in dir_repo.iterdir()] == [".brd"]
    assert brd_dir.is_dir()
    assert (brd_dir / "board.db").read_bytes() == board_bytes
    assert _card_owner("c1") is None
    assert _card_owner("c2") is None


def test_init_project_twice_preserves_existing_cards(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    repo.mkdir()
    project = master.init_project(repo)

    conn = _brd()
    try:
        make_card(conn, "c1", title="Existing card", project_id=project.id)
    finally:
        conn.close()

    master.init_project(repo)

    assert _card_owner("c1") == ("Existing card", project.id)


def test_init_project_upserts_name_on_rerun(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    repo.mkdir()

    master.init_project(repo, name="first-name")
    project = master.init_project(repo, name="second-name")

    assert project.name == "second-name"
    all_projects = master.list_all_projects()
    assert [p.name for p in all_projects] == ["second-name"]


def test_list_all_projects(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo1 = tmp_path / "repo1"
    repo1.mkdir()
    repo2 = tmp_path / "repo2"
    repo2.mkdir()
    master.init_project(repo1)
    master.init_project(repo2)

    results = master.list_all_projects()
    assert {p.name for p in results} == {"repo1", "repo2"}


def test_forget_project_removes_the_registry_row_and_leaves_a_marker_alone(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    repo.mkdir()
    master.init_project(repo)
    (repo / ".brd").write_text("")

    forgotten = master.forget_project(repo)

    assert forgotten.name == "myrepo"
    assert (repo / ".brd").read_text() == ""
    assert master.list_all_projects() == []


def test_forget_project_raises_when_not_registered(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    repo.mkdir()

    with pytest.raises(master.ProjectNotFoundError):
        master.forget_project(repo)


def test_forget_project_works_when_root_path_no_longer_exists(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    repo.mkdir()
    master.init_project(repo)
    shutil.rmtree(repo)

    forgotten = master.forget_project(repo)

    assert forgotten.name == "myrepo"
    assert master.list_all_projects() == []


def test_purge_all_removes_entire_data_dir(tmp_path, monkeypatch):
    data_dir = tmp_path / "data" / "brd"
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo1 = tmp_path / "repo1"
    repo1.mkdir()
    repo2 = tmp_path / "repo2"
    repo2.mkdir()
    master.init_project(repo1)
    master.init_project(repo2)

    removed = master.purge_all()

    assert removed == 2
    assert not data_dir.exists()


def test_purge_all_returns_zero_when_nothing_registered(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    assert master.purge_all() == 0


def test_registry_count_reads_master_db_without_migrating(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    conn = db.connect(paths.master_db_path())
    db.init_master_schema(conn)
    for name in ("a", "b"):
        db.upsert_project(
            conn, Project(db.new_project_id(), name, str(tmp_path / name), "2026-01-01")
        )
    conn.close()

    assert master.registry_count() == 2
    assert not paths.brd_db_path().exists()
    assert paths.master_db_path().is_file()


def test_list_all_projects_is_empty_before_any_registration(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))

    assert master.list_all_projects() == []


def test_forget_removes_the_projects_document_backups(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    repo.mkdir()
    project = master.init_project(repo)
    conn = _brd()
    try:
        make_document(conn, "d1", "notes", content="backup", project_id=project.id)
    finally:
        conn.close()
    backup = paths.docs_dir() / "d1.md"
    assert backup.read_text() == "backup"

    master.forget_project(repo)

    assert not backup.exists()


def _is_uuid4(value):
    return uuid.UUID(value).version == 4 and str(uuid.UUID(value)) == value


def test_init_project_returns_stored_project_with_uuid4_id(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    repo.mkdir()

    project = master.init_project(repo)

    assert _is_uuid4(project.id)
    assert master.list_all_projects() == [project]


def test_init_project_rerun_keeps_id_and_created_at(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    repo.mkdir()

    first = master.init_project(repo, name="first-name")
    second = master.init_project(repo, name="second-name")
    third = master.init_project(repo)

    assert second.id == first.id
    assert second.created_at == first.created_at
    assert second.name == "second-name"
    assert third.id == first.id
    assert third.name == "myrepo"
    assert master.list_all_projects() == [third]


def test_init_project_gives_each_root_its_own_id(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo1 = tmp_path / "repo1"
    repo2 = tmp_path / "repo2"
    repo1.mkdir()
    repo2.mkdir()

    first = master.init_project(repo1)
    second = master.init_project(repo2)

    assert first.id != second.id


def test_init_rerun_keeps_the_brd_db_row_and_its_cards(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo1 = tmp_path / "repo1"
    repo2 = tmp_path / "repo2"
    repo1.mkdir()
    repo2.mkdir()
    first = master.init_project(repo1)
    conn = _brd()
    try:
        make_card(conn, "c1", project_id=first.id)
    finally:
        conn.close()

    master.init_project(repo1, name="renamed")
    other = master.init_project(repo2)

    conn = _brd()
    try:
        stored = {row["root_path"]: tuple(row) for row in conn.execute("SELECT * FROM projects")}
    finally:
        conn.close()
    assert stored[str(repo1)] == (first.id, "renamed", str(repo1), first.created_at)
    assert stored[str(repo2)][0] == other.id != first.id
    assert _card_owner("c1") == ("c1", first.id)


def test_init_on_an_unmigrated_install_keeps_the_registered_id(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    repo.mkdir()
    legacy = Project(db.new_project_id(), "myrepo", str(repo), "2026-01-01T00:00:00+00:00")
    conn = db.connect(paths.master_db_path())
    db.init_master_schema(conn)
    db.upsert_project(conn, legacy)
    conn.close()
    board = db.connect(paths.project_db_path(repo))
    db.migrate_project(board, legacy)
    make_card(board, "c1", project_id=legacy.id)
    board.close()

    project = master.init_project(repo)

    assert (project.id, project.created_at) == (legacy.id, legacy.created_at)
    assert _card_owner("c1") == ("c1", legacy.id)


def test_forget_project_returns_project_with_its_id(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    repo.mkdir()
    project = master.init_project(repo)

    assert master.forget_project(repo) == project


def _resolve(start):
    conn = master.connect()
    try:
        return master.resolve_project(conn, start)
    finally:
        conn.close()


def _not_found(start):
    return f"no registered project at or above {start.resolve()}; run `brd init` there"


def test_resolve_project_at_the_registered_root(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    repo.mkdir()
    project = master.init_project(repo)

    assert _resolve(repo) == project


def test_resolve_project_from_a_nested_subdirectory(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "myrepo"
    nested = repo / "a" / "b"
    nested.mkdir(parents=True)
    project = master.init_project(repo)

    assert _resolve(nested) == project


@pytest.mark.parametrize("deeper_first", [False, True])
def test_resolve_project_picks_the_deepest_registered_root(tmp_path, monkeypatch, deeper_first):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    outer = tmp_path / "r"
    inner = outer / "sub"
    (inner / "x").mkdir(parents=True)
    (outer / "other").mkdir()
    if deeper_first:
        inner_project = master.init_project(inner)
        outer_project = master.init_project(outer)
    else:
        outer_project = master.init_project(outer)
        inner_project = master.init_project(inner)

    assert _resolve(inner / "x") == inner_project
    assert _resolve(inner) == inner_project
    assert _resolve(outer / "other") == outer_project
    assert _resolve(outer) == outer_project


def test_resolve_project_matches_whole_path_components(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "repo"
    sibling = tmp_path / "repo2"
    repo.mkdir()
    sibling.mkdir()
    master.init_project(repo)

    with pytest.raises(master.ProjectNotFoundError):
        _resolve(sibling)


def test_resolve_project_with_nothing_registered_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))

    with pytest.raises(master.ProjectNotFoundError) as excinfo:
        _resolve(tmp_path)

    assert str(excinfo.value) == _not_found(tmp_path)


def test_resolve_project_outside_any_root_names_the_path_and_brd_init(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    registered = tmp_path / "registered"
    plain = tmp_path / "plain"
    marked = tmp_path / "marked"
    for directory in (registered, plain, marked):
        directory.mkdir()
    (marked / ".brd").write_text("")
    master.init_project(registered)

    with pytest.raises(master.ProjectNotFoundError) as plain_error:
        _resolve(plain)
    with pytest.raises(master.ProjectNotFoundError) as marked_error:
        _resolve(marked)

    assert str(plain_error.value) == _not_found(plain)
    assert str(marked_error.value) == _not_found(marked)
    assert "brd init" in str(plain_error.value)


def test_resolve_project_treats_percent_and_underscore_literally(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    wild = tmp_path / "a_%b"
    lookalike = tmp_path / "aXYb"
    (wild / "x").mkdir(parents=True)
    lookalike.mkdir()
    project = master.init_project(wild)

    assert _resolve(wild) == project
    assert _resolve(wild / "x") == project
    with pytest.raises(master.ProjectNotFoundError):
        _resolve(lookalike)


def test_resolve_project_follows_a_symlinked_start(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "repo"
    (repo / "a").mkdir(parents=True)
    project = master.init_project(repo)
    link = tmp_path / "link"
    link.symlink_to(repo, target_is_directory=True)

    assert _resolve(link / "a") == project


def test_resolve_project_reaches_a_project_registered_at_the_filesystem_root(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "repo"
    repo.mkdir()
    conn = master.connect()
    try:
        top = db.upsert_project(
            conn, Project(db.new_project_id(), "top", "/", "2026-01-01T00:00:00+00:00")
        )
        deeper = db.upsert_project(
            conn, Project(db.new_project_id(), "repo", str(repo), "2026-01-01T00:00:00+00:00")
        )

        assert master.resolve_project(conn, tmp_path) == top
        assert master.resolve_project(conn, repo) == deeper
    finally:
        conn.close()


def test_resolve_project_ignores_a_brd_marker_in_an_unregistered_subdirectory(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "repo"
    sub = repo / "sub"
    sub.mkdir(parents=True)
    project = master.init_project(repo)
    (sub / ".brd").write_text("")

    assert _resolve(sub) == project


def test_resolve_project_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "repo"
    repo.mkdir()
    project = master.init_project(repo)
    conn = master.connect()
    try:
        before = conn.total_changes

        assert master.resolve_project(conn, repo) == project
        with pytest.raises(master.ProjectNotFoundError):
            master.resolve_project(conn, tmp_path / "elsewhere")

        assert conn.total_changes == before
        assert not conn.in_transaction
    finally:
        conn.close()


def test_init_project_inside_a_registered_project_adds_a_nested_one(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    outer = tmp_path / "r"
    inner = outer / "sub"
    (inner / "x").mkdir(parents=True)

    outer_project = master.init_project(outer)
    inner_project = master.init_project(inner)

    assert inner_project.id != outer_project.id
    assert {p.root_path for p in master.list_all_projects()} == {str(outer), str(inner)}
    assert _resolve(inner / "x") == inner_project
    assert list(inner.iterdir()) == [inner / "x"]


def test_forgetting_a_nested_project_hands_its_tree_back_to_the_outer_one(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    outer = tmp_path / "r"
    inner = outer / "sub"
    (inner / "x").mkdir(parents=True)
    outer_project = master.init_project(outer)
    master.init_project(inner)

    master.forget_project(inner)

    assert _resolve(inner / "x") == outer_project
    assert master.list_all_projects() == [outer_project]


def _moved_repo(tmp_path, monkeypatch):
    """A project registered at old/ with one card, and an empty new/."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    new.mkdir()
    project = master.init_project(old)
    conn = _brd()
    try:
        make_card(conn, "c1", title="Moved card", project_id=project.id)
    finally:
        conn.close()
    return project, old, new


def test_relink_project_by_old_root_points_the_project_at_the_new_root(
    tmp_path, monkeypatch
):
    project, old, new = _moved_repo(tmp_path, monkeypatch)

    relinked = master.relink_project(new, str(old))

    assert relinked == Project(project.id, project.name, str(new), project.created_at)
    assert master.list_all_projects() == [relinked]
    assert _card_owner("c1") == ("Moved card", project.id)
    assert _resolve(new / "sub") == relinked
    with pytest.raises(ProjectNotFoundError):
        _resolve(old)


def test_relink_project_by_id_after_the_old_directory_is_gone(tmp_path, monkeypatch):
    project, old, new = _moved_repo(tmp_path, monkeypatch)
    shutil.rmtree(old)

    relinked = master.relink_project(new, project.id)

    assert relinked == Project(project.id, project.name, str(new), project.created_at)
    assert master.list_all_projects() == [relinked]
    assert _card_owner("c1") == ("Moved card", project.id)


@pytest.mark.parametrize("spelling", ["{old}/", "{old}/../old", "{old}/./"])
def test_relink_project_normalises_the_old_root(tmp_path, monkeypatch, spelling):
    project, old, new = _moved_repo(tmp_path, monkeypatch)

    relinked = master.relink_project(new, spelling.format(old=old))

    assert (relinked.id, relinked.root_path) == (project.id, str(new))


def test_relink_project_accepts_a_relative_old_root(tmp_path, monkeypatch):
    project, old, new = _moved_repo(tmp_path, monkeypatch)

    relinked = master.relink_project(new, "../old")

    assert (relinked.id, relinked.root_path) == (project.id, str(new))


def test_relink_project_keeps_the_name_unless_one_is_given(tmp_path, monkeypatch):
    project, old, new = _moved_repo(tmp_path, monkeypatch)

    kept = master.relink_project(new, str(old))
    assert kept.name == "old"

    renamed = master.relink_project(new, project.id, name="renamed")
    assert renamed.name == "renamed"
    assert renamed.root_path == str(new)


def test_relink_project_already_at_the_cwd_changes_nothing(tmp_path, monkeypatch):
    project, old, new = _moved_repo(tmp_path, monkeypatch)

    assert master.relink_project(old, str(old)) == project
    assert master.relink_project(old, project.id) == project
    assert master.list_all_projects() == [project]


@pytest.mark.parametrize("ref", [str(uuid.uuid4()), "/never/registered"])
def test_relink_project_with_an_unknown_ref_is_not_found(tmp_path, monkeypatch, ref):
    project, old, new = _moved_repo(tmp_path, monkeypatch)

    with pytest.raises(ProjectNotFoundError) as excinfo:
        master.relink_project(new, ref)

    assert ref in str(excinfo.value)
    assert "brd projects" in str(excinfo.value)
    assert master.list_all_projects() == [project]


def test_relink_project_with_empty_ref_is_not_found(tmp_path, monkeypatch):
    # "" normalises to the cwd itself; it must not match the cwd's project.
    project, old, new = _moved_repo(tmp_path, monkeypatch)

    with pytest.raises(ProjectNotFoundError):
        master.relink_project(old, "")

    assert master.list_all_projects() == [project]


def test_relink_project_onto_another_projects_root_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    project_a = master.init_project(a)
    project_b = master.init_project(b)

    with pytest.raises(ProjectAlreadyExistsError) as excinfo:
        master.relink_project(b, project_a.id)

    message = str(excinfo.value)
    assert str(b) in message
    assert project_b.name in message
    assert project_b.id in message
    assert sorted(master.list_all_projects(), key=lambda p: p.id) == sorted(
        [project_a, project_b], key=lambda p: p.id
    )


def test_relink_project_refusal_leaves_the_database_writable(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    a = tmp_path / "a"
    b = tmp_path / "b"
    c = tmp_path / "c"
    for d in (a, b, c):
        d.mkdir()
    project_a = master.init_project(a)
    master.init_project(b)
    with pytest.raises(ProjectAlreadyExistsError):
        master.relink_project(b, project_a.id)

    # A lock or a half-applied update left behind would show up here.
    project_c = master.init_project(c)

    assert {p.root_path for p in master.list_all_projects()} == {str(a), str(b), str(c)}
    assert _resolve(c) == project_c
    assert _resolve(a) == project_a


def test_relink_project_into_another_projects_tree_nests_it(tmp_path, monkeypatch):
    project, old, new = _moved_repo(tmp_path, monkeypatch)
    outer = tmp_path / "outer"
    inner = outer / "inner"
    (inner / "x").mkdir(parents=True)
    (outer / "y").mkdir()
    outer_project = master.init_project(outer)

    relinked = master.relink_project(inner, str(old))

    assert relinked.id == project.id
    assert _resolve(inner / "x") == relinked
    assert _resolve(outer / "y") == outer_project


def _two_projects(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    return master.init_project(a), master.init_project(b)


def _count(sql, *params):
    conn = _brd()
    try:
        return conn.execute(sql, params).fetchone()[0]
    finally:
        conn.close()


def test_forget_project_by_id_removes_what_it_owns_and_nothing_else(tmp_path, monkeypatch):
    project_a, project_b = _two_projects(tmp_path, monkeypatch)
    conn = _brd()
    try:
        make_card(conn, "ca", project_id=project_a.id)
        make_issue(conn, "ia", project_id=project_a.id)
        make_document(conn, "da", "a-notes", content="a", project_id=project_a.id)
        make_card(conn, "cb", project_id=project_b.id)
        make_document(conn, "db", "b-notes", content="b", project_id=project_b.id)
        with conn:
            for entity_id in ("ca", "cb"):
                conn.execute(
                    "INSERT INTO comments (id, entity_id, author, body, created_at) "
                    "VALUES (?, ?, 'me', 'hi', 'now')",
                    (f"cm-{entity_id}", entity_id),
                )
                conn.execute(
                    "INSERT INTO tags (entity_id, tag) VALUES (?, 'x')", (entity_id,)
                )
    finally:
        conn.close()

    assert master.forget_project_by_id(project_a.id) == project_a

    assert master.list_all_projects() == [project_b]
    assert _count("SELECT COUNT(*) FROM entities WHERE project_id = ?", project_a.id) == 0
    for table in ("cards", "issues", "documents"):
        assert _count(f"SELECT COUNT(*) FROM {table} WHERE id IN ('ca', 'ia', 'da')") == 0
    assert _count("SELECT COUNT(*) FROM comments WHERE entity_id = 'ca'") == 0
    assert _count("SELECT COUNT(*) FROM tags WHERE entity_id = 'ca'") == 0
    assert not (paths.docs_dir() / "da.md").exists()
    assert _count("SELECT COUNT(*) FROM entities WHERE project_id = ?", project_b.id) == 2
    assert _count("SELECT COUNT(*) FROM comments WHERE entity_id = 'cb'") == 1
    assert _count("SELECT COUNT(*) FROM tags WHERE entity_id = 'cb'") == 1
    assert (paths.docs_dir() / "db.md").read_text() == "b"


def test_forget_project_by_id_works_when_the_root_is_gone_and_cwd_is_unregistered(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "repo"
    elsewhere = tmp_path / "elsewhere"
    repo.mkdir()
    elsewhere.mkdir()
    project = master.init_project(repo)
    shutil.rmtree(repo)
    monkeypatch.chdir(elsewhere)

    assert master.forget_project_by_id(project.id) == project
    assert master.list_all_projects() == []


def test_forget_project_by_id_with_an_unknown_id_is_not_found(tmp_path, monkeypatch):
    project_a, project_b = _two_projects(tmp_path, monkeypatch)
    unknown = str(uuid.uuid4())

    with pytest.raises(ProjectNotFoundError) as excinfo:
        master.forget_project_by_id(unknown)

    assert unknown in str(excinfo.value)
    assert "brd projects" in str(excinfo.value)
    assert len(master.list_all_projects()) == 2


def test_forget_project_by_id_does_not_match_a_root_path(tmp_path, monkeypatch):
    project_a, project_b = _two_projects(tmp_path, monkeypatch)

    with pytest.raises(ProjectNotFoundError):
        master.forget_project_by_id(project_a.root_path)

    assert len(master.list_all_projects()) == 2


def test_forgetting_a_project_removes_edges_other_projects_point_at_it(
    tmp_path, monkeypatch
):
    project_a, project_b = _two_projects(tmp_path, monkeypatch)
    conn = _brd()
    try:
        make_card(conn, "a1", project_id=project_a.id)
        make_card(conn, "b1", project_id=project_b.id)
        make_card(conn, "b2", status="done", project_id=project_b.id)
        db.add_blocked_by_edge(conn, "b1", "a1")
        db.add_blocked_by_edge(conn, "b1", "b2")
        with conn:
            for dst in ("a1", "b2"):
                conn.execute(
                    "INSERT INTO refs (src_id, dst_id, origin) VALUES ('b1', ?, 'explicit')",
                    (dst,),
                )
        assert core.resolve_status(conn, db.get_card(conn, "b1")) == "blocked"
    finally:
        conn.close()

    master.forget_project_by_id(project_a.id)

    conn = _brd()
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM blocked_by WHERE blocks_on_id = 'a1'"
        ).fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM refs WHERE dst_id = 'a1'").fetchone()[0] == 0
        assert db.list_blockers_of(conn, "b1") == ["b2"]
        assert [r["dst_id"] for r in conn.execute("SELECT dst_id FROM refs")] == ["b2"]
        assert core.resolve_status(conn, db.get_card(conn, "b1")) == "todo"
    finally:
        conn.close()


def test_forget_current_project_forgets_the_deepest_root_above_the_cwd(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "repo"
    deeper = repo / "sub" / "deeper"
    deeper.mkdir(parents=True)
    project = master.init_project(repo)

    assert master.forget_current_project(deeper) == project
    assert master.list_all_projects() == []


def test_forget_current_project_inside_a_nested_project_forgets_only_it(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    outer = tmp_path / "repo"
    inner = outer / "inner"
    (inner / "x").mkdir(parents=True)
    outer_project = master.init_project(outer)
    inner_project = master.init_project(inner)

    assert master.forget_current_project(inner / "x") == inner_project
    assert master.list_all_projects() == [outer_project]


def test_forget_current_project_outside_any_project_is_not_found(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    nowhere = tmp_path / "nowhere"
    nowhere.mkdir()

    with pytest.raises(ProjectNotFoundError) as excinfo:
        master.forget_current_project(nowhere)

    assert str(excinfo.value) == _not_found(nowhere)
