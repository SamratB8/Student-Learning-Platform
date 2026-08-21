"""Application layer: use cases and the ports they depend on.

This layer orchestrates. It owns transaction boundaries and declares interfaces that
infrastructure and integrations implement. It imports ``domain`` only, so a use case
can be exercised from a web request, a background handler, or a test without change.

No module here may read Flask request globals or import a provider SDK.
"""
