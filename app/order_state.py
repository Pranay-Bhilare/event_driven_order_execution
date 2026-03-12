"""
Order lifecycle state machine. Valid transitions enforce business rules.
"""

# Current state -> allowed next event_type
VALID_TRANSITIONS = {
    None: ["ORDER_CREATED"],
    "ORDER_CREATED": ["PAYMENT_CONFIRMED", "ORDER_CANCELLED"],
    "PAYMENT_CONFIRMED": ["ORDER_SHIPPED", "ORDER_CANCELLED"],
    "ORDER_SHIPPED": ["ORDER_DELIVERED", "ORDER_CANCELLED"], # Return flow alag hota hai
    "ORDER_DELIVERED": [],
    "ORDER_CANCELLED": [], # Terminal state
}


def is_valid_transition(current_state: str | None, new_event_type: str) -> bool:
    """True if new_event_type is allowed after current_state."""
    allowed = VALID_TRANSITIONS.get(current_state, [])
    return new_event_type in allowed
