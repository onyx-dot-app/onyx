import os
import sys


# Ensure PYTHONPATH is set up for direct script execution
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
print(parent_dir)
sys.path.append(parent_dir)

from onyx.db.engine.sql_engine import get_session_with_current_tenant  # noqa: E402
from onyx.db.engine.sql_engine import SqlEngine  # noqa: E402
from onyx.db.models import ChatSession  # noqa: E402
from onyx.db.chat import delete_chat_session  # noqa: E402


def main() -> None:
    SqlEngine.init_engine(pool_size=20, max_overflow=5)

    with get_session_with_current_tenant() as db_session:
        deleted_sessions = (
            db_session.query(ChatSession).filter(ChatSession.deleted.is_(True)).all()
        )
        if not deleted_sessions:
            print("No deleted chat sessions found.")
            return
        print(f"Found {len(deleted_sessions)} deleted chat sessions:")
        for session in deleted_sessions:
            print(f"  - ID: {session.id} | deleted: {session.deleted}")
        confirm = input(
            "\nAre you sure you want to hard delete these sessions? Type 'yes' to confirm: "
        )
        if confirm.strip().lower() != "yes":
            print("Aborted by user.")
            return
        total = 0
        for session in deleted_sessions:
            print(f"Deleting {session.id}")
            try:
                delete_chat_session(
                    user_id=None,
                    chat_session_id=session.id,
                    db_session=db_session,
                    include_deleted=True,
                    hard_delete=True,
                )
                total += 1
            except Exception as e:
                print(f"Error deleting session {session.id}: {e}")
        print(f"Deleted {total}")


if __name__ == "__main__":
    main()
