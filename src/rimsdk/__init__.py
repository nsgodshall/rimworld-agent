"""Typed Python SDK for RimWorld, over the RimMCP mod's local HTTP bridge.

    from rimsdk import RimClient

    with RimClient.connect() as rim:
        status = rim.get_colony_status()
        run = rim.advance(6)
"""

from . import errors
from ._generated import MANIFEST_VERSION
from .client import CallRecord, ManifestDrift, RimClient
from .result import Result
from .transport import NO_RETRY, RetryPolicy

__all__ = ["MANIFEST_VERSION", "NO_RETRY", "CallRecord", "ManifestDrift", "Result", "RetryPolicy", "RimClient", "errors"]
