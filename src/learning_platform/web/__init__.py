"""Web layer: HTTP composition.

This is the composition root. It builds settings, constructs adapters, wires them
into the application layer, and translates between HTTP and use cases. It is the only
layer permitted to touch Flask request globals.
"""

from learning_platform.web.app import create_app

__all__ = ["create_app"]
