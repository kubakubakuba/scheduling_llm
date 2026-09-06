"""Compatibility entry point for the configurable benchmark runner.

The executable lives in :mod:`benchmark.bench`; this module keeps the
historical ``benchmark.run`` import and command spelling usable.
"""

if __package__:
    from .bench import *  # noqa: F401,F403
    from .bench import (
        _read_json,
        _reference_for_case,
        _compact_history,
        _compact_tool_result,
        _validate_tool_args,
    )
else:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from benchmark.bench import *  # noqa: F401,F403
    from benchmark.bench import (
    _read_json,
    _reference_for_case,
    _compact_history,
    _compact_tool_result,
    _validate_tool_args,
    )


if __name__ == "__main__":
    from benchmark.bench import app

    app()
