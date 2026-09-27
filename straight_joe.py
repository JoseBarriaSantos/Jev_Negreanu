import random

from strength import hand_strength

NAME = "Straight Joe"
SHORT_NAME = "Joe"
RAISE_FROM = 0.6
ALWAYS_RAISE_AT = 0.9


def play(state):
    """Straight Joe never bluffs: every move comes straight from the hand's
    strength (chance of beating a random hand).

    - Raise: never below 0.6, always above 0.9, and more often in between
      (0.8 raises 2 out of 3 times). The size grows with strength, from 20% of
      the pot at 0.6 up to the whole pot at 1.0.
    - Call: when the chance of winning is at least the share of the final pot
      we'd be paying (calling 20 into a pot of 80 is paying 20% of 100).
    - Fold: otherwise. Checks instead whenever checking is free.

    Returns the name of the move it played.
    """
    seat = state.actor_index
    strength = hand_strength(state, seat)
    to_call = state.checking_or_calling_amount
    pot_after_call = state.total_pot_amount + to_call
    raise_chance = (strength - RAISE_FROM) / (ALWAYS_RAISE_AT - RAISE_FROM)

    if state.can_complete_bet_or_raise_to() and random.random() < raise_chance:
        max_to = state.max_completion_betting_or_raising_to_amount
        size = pot_after_call * 2 * (strength - 0.5)
        amount = round(max(state.bets) + size)
        amount = max(amount, state.min_completion_betting_or_raising_to_amount)
        amount = min(amount, max_to)
        state.complete_bet_or_raise_to(amount)
        return f"all-in (to {amount})" if amount == max_to else f"raise to {amount}"
    if to_call == 0 or strength >= to_call / pot_after_call:
        state.check_or_call()
        return "check" if to_call == 0 else f"call {to_call}"
    state.fold()
    return "fold"
