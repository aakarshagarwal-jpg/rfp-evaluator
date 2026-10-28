"""Create the SQLite database and seed sample evaluation criteria.

Usage:
    python -m db.seed           # create if missing, seed if empty
    python -m db.seed --reset   # delete the DB file and recreate from scratch
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.database import DEFAULT_DB_PATH, get_active_criteria, init_db, validate_criteria  # noqa: E402


def main() -> None:
    if "--reset" in sys.argv and Path(DEFAULT_DB_PATH).exists():
        Path(DEFAULT_DB_PATH).unlink()
        print(f"Deleted {DEFAULT_DB_PATH}")
    init_db(DEFAULT_DB_PATH, seed=True)
    criteria = get_active_criteria(DEFAULT_DB_PATH)
    errors = validate_criteria(criteria)
    print(f"Database ready at {DEFAULT_DB_PATH}")
    for c in criteria:
        print(f"  [{c['criterion_id']}] {c['name']:<24} weight={c['weight']:>5g}%  max={c['max_score']}")
    print("Weights OK (total 100%)" if not errors else "\n".join(errors))


if __name__ == "__main__":
    main()
