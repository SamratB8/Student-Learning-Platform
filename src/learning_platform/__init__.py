"""Student Learning Platform.

The importable package is ``learning_platform`` rather than ``platform`` because
``platform`` is a standard-library module and would be shadowed whenever ``src``
reaches the front of ``sys.path``. See docs/ARCHITECTURE.md.

Layering, enforced by tests/architecture:

    web / worker  ->  application  ->  domain
    infrastructure / integrations  ->  application  ->  domain

``domain`` imports no framework. ``application`` declares ports. ``infrastructure``
and ``integrations`` implement them. ``web`` composes.
"""

__all__ = ["__version__"]

__version__ = "0.1.0"
