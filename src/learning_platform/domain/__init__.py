"""Framework-neutral domain layer.

This package must not import Flask, SQLAlchemy, Alembic, pydantic, or any provider
SDK. It holds entities, value objects, policies, and errors that stay true whether
they are exercised by a web request, a background handler, or a test.
"""
