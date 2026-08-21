"""Background task handlers.

Handlers live here and share the domain and application packages, exactly as ADR 0001
described. What has changed under ADR 0002 is how they are invoked: there is no
always-running colocated process, and ADR 0004 has not yet chosen a runtime.

A handler therefore takes a payload and does its work. It does not own a main loop, a
scheduler, or a connection to a broker. Whatever runtime is chosen calls it.

Every handler must be idempotent, must take only internal identifiers in its payload,
and must not assume it runs in the same process or region as the request that
dispatched it.

No handlers exist yet, because no feature needs one. They are added with the work
that requires them.
"""
