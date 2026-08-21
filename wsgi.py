"""WSGI entry point for the Vercel Python runtime.

Vercel's Python runtime loads a WSGI application from a supported entrypoint and
expects a top-level name ``app``. ``pyproject.toml`` points at this module through
``[tool.vercel] entrypoint``, so detection is explicit rather than inferred from the
repository layout.

This file is a hosting adapter and nothing else. It contains no configuration, no
routes, and no product logic. ``create_app`` remains the single composition root, and
this module exists only because the platform needs a module-level name to import.
Anything that belongs to the application belongs in ``learning_platform.web``.

On import-time construction and ADR 0002:

    ADR 0002 forbids a module-level Flask singleton that holds state, and forbids
    background threads or schedulers started at import. Building the application once
    per function instance does not violate that. The object created here holds no
    request-scoped state: configuration is immutable, the correlation identifier lives
    in a context variable bound per request, and constructing the SQLAlchemy engine
    opens no connection. Reusing it across invocations of one warm instance is the
    intended serverless shape, and it is what keeps cold starts to a single build.

On asserting hosted execution:

    ``load_hosted_settings`` is used rather than the plain loader because importing
    this module proves a hosting platform imported it. That is a stronger fact than
    sniffing for platform environment variables, all of which depend on a project
    setting that can be switched off. Without the assertion, a deployment with that
    setting disabled would see no markers, conclude it was running locally, and serve
    a public URL with development defaults. Stating the fact here is the whole reason
    this module exists as a separate entry point, and it remains a hosting concern
    rather than application logic.

If required configuration is missing, or the deployment's environment cannot be
identified, this raises at import and the function fails to boot. That is deliberate:
a deployment that cannot be configured safely must not serve requests.
"""

from __future__ import annotations

from learning_platform.infrastructure.config import load_hosted_settings
from learning_platform.web import create_app

__all__ = ["app"]

app = create_app(load_hosted_settings())
