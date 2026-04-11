"""
Pytest configuration: block real network (TCP/UDP) access during tests.
"""

import os
import sys
import socket
import pytest

# verify_isolation.py lives in cluster/agent/isolation/ after refactoring.
# Add that directory to sys.path so `import verify_isolation` works when
# running tests from cluster/agent/codex/.
_isolation_dir = os.path.join(os.path.dirname(__file__), "..", "isolation")
if _isolation_dir not in sys.path:
    sys.path.insert(0, os.path.abspath(_isolation_dir))


_real_socket = socket.socket


class _BlockedSocket(_real_socket):
    """Socket subclass that raises on AF_INET / AF_INET6 creation."""

    def __init__(self, family=socket.AF_INET, *args, **kwargs):
        if family in (socket.AF_INET, socket.AF_INET6):
            raise OSError("Network access blocked in tests")
        super().__init__(family, *args, **kwargs)


@pytest.fixture(autouse=True, scope="session")
def block_network():
    """Replace socket.socket with a version that rejects internet connections."""
    socket.socket = _BlockedSocket
    yield
    socket.socket = _real_socket
