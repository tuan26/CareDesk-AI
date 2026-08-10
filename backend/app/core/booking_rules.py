"""Rules about when a slot is taken.

Kept in one module because three places have to agree on it — the slot finder,
the booking endpoint's conflict check, and the database's unique index. When
they disagree the symptom is two patients arriving for the same time.
"""

STATUS_PENDING = "pending"
STATUS_AWAITING_DEPOSIT = "awaiting_deposit"
STATUS_CONFIRMED = "confirmed"
STATUS_CANCELLED = "cancelled"
STATUS_COMPLETED = "completed"
STATUS_NO_SHOW = "no_show"

#: Statuses that occupy the doctor's calendar. ``awaiting_deposit`` belongs here
#: and used to be missing: a patient who had been asked for a deposit and was
#: away paying it had their slot offered to the next person who asked.
SLOT_HOLDING_STATUSES = (STATUS_PENDING, STATUS_AWAITING_DEPOSIT, STATUS_CONFIRMED)

#: Statuses that free the slot again.
SLOT_RELEASING_STATUSES = (STATUS_CANCELLED, STATUS_NO_SHOW)
