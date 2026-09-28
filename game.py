from functools import partial

from pokerkit import Automation, NoLimitTexasHoldem

STREETS = ("pre-flop", "flop", "turn", "river")
STARTING_STACK = 200
BLINDS = (1, 2)
POT_SIZES = {
    "1/3 pot": 1 / 3,
    "1/2 pot": 1 / 2,
    "2/3 pot": 2 / 3,
    "3/4 pot": 3 / 4,
    "1 pot": 1,
    "1.5 pot": 1.5,
}


def new_state():
    return NoLimitTexasHoldem.create_state(
        (
            Automation.ANTE_POSTING,
            Automation.BET_COLLECTION,
            Automation.BLIND_OR_STRADDLE_POSTING,
            Automation.CARD_BURNING,
            Automation.HOLE_DEALING,
            Automation.BOARD_DEALING,
            Automation.RUNOUT_COUNT_SELECTION,
            Automation.HOLE_CARDS_SHOWING_OR_MUCKING,
            Automation.HAND_KILLING,
            Automation.CHIPS_PUSHING,
            Automation.CHIPS_PULLING,
        ),
        True,
        0,
        BLINDS,
        BLINDS[1],
        (STARTING_STACK, STARTING_STACK),
        2,
    )


def legal_moves(state):
    """Map the name of each move allowed right now to the function that plays it.

    Every bet and raise is a share of the pot, on every street:
    - Bet (nobody has bet yet): that share of the pot. "1/2 pot" into 36 bets 18.
    - Raise (there's a bet to beat, including the big blind before the flop): call
      first in your head, then add that share of the pot as it would be after the
      call. Opening pre-flop, the pot after calling is 4, so "1 pot" raises to
      2 + 4 = 6 (3 big blinds). Facing a bet of 18 into 36, it's 18 + 72 = 90.
    Sizes below the smallest legal bet become that bet, named "min". Sizes that
    land on the same amount are shown once, and sizes that reach the whole stack
    are left to "all-in".
    """
    moves = {}
    if state.can_fold():
        moves["fold"] = state.fold
    if state.can_check_or_call():
        amount = state.checking_or_calling_amount
        moves["check" if amount == 0 else f"call {amount}"] = state.check_or_call
    if state.can_complete_bet_or_raise_to():
        min_to = state.min_completion_betting_or_raising_to_amount
        max_to = state.max_completion_betting_or_raising_to_amount
        verb = bet_or_raise(state)
        names = {}
        for name, share in POT_SIZES.items():
            size = pot_size_to(state, share)
            amount = max(size, min_to)
            if amount < max_to and names.get(amount, "min") == "min":
                names[amount] = name if size >= min_to else "min"
        for amount, name in sorted(names.items()):
            moves[f"{verb} {name} (to {amount})"] = partial(state.complete_bet_or_raise_to, amount)
        moves[f"all-in (to {max_to})"] = partial(state.complete_bet_or_raise_to, max_to)
    return moves


def bet_or_raise(state):
    return "raise" if max(state.bets) else "bet"


def pot_size_to(state, share):
    """The amount to bet or raise to for a share of the pot (see legal_moves)."""
    to_beat = max(state.bets)
    pot_after_call = state.total_pot_amount + state.checking_or_calling_amount
    return round(to_beat + share * pot_after_call)


def bet_to_name(state, amount):
    """Name for betting or raising to any amount, e.g. from the web page's slider."""
    if amount == state.max_completion_betting_or_raising_to_amount:
        return f"all-in (to {amount})"
    return f"{bet_or_raise(state)} to {amount}"


def short(cards):
    return " ".join(map(repr, cards))
