"""
Pytest configuration: block real network (TCP/UDP) access during tests.
"""

import socket
import pytest


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
