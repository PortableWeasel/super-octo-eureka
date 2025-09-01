from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from git_mirror.core import parse_repo_id
from git_mirror.gitolite import gitolite_path_for


def test_parse_repo_id_preserves_full_path(tmp_path: Path) -> None:
    url = "https://gitlab.com/group/sub/repo.git"
    rid = parse_repo_id(url)
    assert rid.host == "gitlab.com"
    assert rid.path == ("group", "sub", "repo")
    assert rid.owner == "group"
    assert rid.name == "repo"
    expected = tmp_path / "gitlab.com" / "group" / "sub" / "repo.git"
    assert rid.mirror_dir(tmp_path) == expected
    assert gitolite_path_for(rid) == "mirrors/gitlab.com/group/sub/repo.git"
