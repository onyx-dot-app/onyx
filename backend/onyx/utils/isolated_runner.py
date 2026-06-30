"""Child entry for ``run_in_isolated_process``: read a pickled (callable, args,
kwargs) from stdin, run it, and write the pickled result back over a private copy
of stdout.

Run as ``python -m onyx.utils.isolated_runner`` so it works even when the caller is
a daemon (the indexing worker), which can't spawn multiprocessing children.
"""

import os
import sys


def main() -> None:
    # Keep a private copy of real stdout for the result, then send stdout/stderr to
    # devnull so imports or native-lib chatter can't corrupt the pickled result.
    result_fd = os.dup(1)
    devnull = os.open(os.devnull, os.O_WRONLY)
    os.dup2(devnull, 1)
    os.dup2(devnull, 2)
    os.close(devnull)

    import pickle

    from onyx.utils.process_isolation import STATUS_EXC
    from onyx.utils.process_isolation import STATUS_OK
    from onyx.utils.process_isolation import STATUS_UNRELAYABLE

    fn, args, kwargs = pickle.loads(sys.stdin.buffer.read())  # noqa: S301
    try:
        payload = (STATUS_OK, fn(*args, **kwargs))
    except Exception as e:
        payload = (STATUS_EXC, e)

    try:
        data = pickle.dumps(payload)
    except Exception:
        # Result or exception didn't pickle; relay its repr so the parent still raises.
        data = pickle.dumps((STATUS_UNRELAYABLE, repr(payload[1])))

    os.write(result_fd, data)
    os.close(result_fd)


if __name__ == "__main__":
    main()
