"""Layered, scoped role-based access control.

Permissions are code-declared strings (``"institution.memberships.verify"``)
contributed by modules. Roles bundle permissions and are assigned to users
*at a scope*: the whole platform, or one institution, campus, community …
A grant on a parent scope applies to its children (campus -> institution)
through scope resolvers registered by modules.

Public API::

    from university.permissions.services import has_permission, authorize, Scope
    from university.permissions.drf import require_permission
"""
