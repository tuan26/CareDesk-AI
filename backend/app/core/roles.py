"""The role vocabulary, in one place.

Inside a clinic there are exactly two roles: the person who runs it and the
person at the front desk.

A third clinic role, ``admin``, used to exist. It carried permissions identical
to ``owner`` — every endpoint that accepted one accepted the other, and
``verify_admin`` was never wired to anything — but it was *worse* in two silent
ways: the 8h/20h operations digest (services/reminder.py) and the platform
console's "Chủ phòng khám" column (services/tenant_stats.py) both look up
``role == "owner"``, so an ``admin`` received neither. Because the name implies
seniority it was a trap: promote a manager to "admin" and their daily digest
quietly stops. Migration c9d0e1f2a3b4 folded it into ``owner``.
"""

ROLE_OWNER = "owner"
ROLE_RECEPTIONIST = "receptionist"

#: Roles that may be assigned to a member of staff within a clinic.
CLINIC_ROLES = (ROLE_OWNER, ROLE_RECEPTIONIST)

# Above a clinic. Neither is a clinic role: these accounts have clinic_id=NULL
# and reach a clinic only by explicitly stepping into one, at which point
# get_current_user maps them onto ROLE_OWNER for that request.
ROLE_ORG_OWNER = "org_owner"   # owns a chain of clinics
ROLE_PLATFORM = "platform"     # the vendor (paired with is_platform_admin)

ABOVE_CLINIC_ROLES = (ROLE_ORG_OWNER, ROLE_PLATFORM)

ALL_ROLES = CLINIC_ROLES + ABOVE_CLINIC_ROLES
