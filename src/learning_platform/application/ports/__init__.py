"""Ports: interfaces the application depends on and infrastructure implements.

Defined as ``typing.Protocol`` so implementations do not inherit from an application
base class. That keeps the dependency arrow pointing inwards and lets a test supply a
plain object.
"""
