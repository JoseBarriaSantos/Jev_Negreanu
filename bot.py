import time
from functools import partial

from dotenv import load_dotenv
from pokerkit import Automation, NoLimitTexasHoldem
from typesafe_sdk import Choice, TypeSafeClient

import straight_joe as opponent
from stats import STREETS, save_batch
from strength import hand_strength

JEV_VERSION = "1.1"
JEV_VERSIONS = {
    "1.0": "Base version: sees its cards, the board, pot, chips and bets, and picks from the legal moves.",
    "1.1": "Hand strength (chance of beating a random hand) added to the instructions.",
}

HANDS = 100
STARTING_STACK = 200
BLINDS = (1, 2)
RAISE_MULTIPLIERS = (1, 1.5, 2, 2.5, 3)


def instructions(strength):
    return (
        "You are playing heads-up No-Limit Texas Hold'em. "
        f"Your hand strength is {strength:.0%}: the chance your hand beats a random hand "
        "once all the cards are dealt. "
        "Pick the move that wins the most chips in the long run."
    )


def new_hand():
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


def describe(state, seat):
    opponent = 1 - seat
    return {
        "street": STREETS[state.street_index],
        "your_cards": " ".join(map(str, state.hole_cards[seat])),
        "board_cards": " ".join(map(str, state.get_board_cards(0))) or "none",
        "pot": state.total_pot_amount,
        "your_chips": state.stacks[seat],
        "opponent_chips": state.stacks[opponent],
        "your_bet_this_round": state.bets[seat],
        "opponent_bet_this_round": state.bets[opponent],
    }


def legal_moves(state):
    """Map the name of each move allowed right now to the function that plays it.

    Raise sizes are multiples of the smallest raise allowed. Sizes that would
    reach our whole stack are dropped, since "all-in" already covers them.
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
        for multiplier in RAISE_MULTIPLIERS:
            amount = round(min_to * multiplier)
            if amount < max_to:
                moves[f"raise {multiplier}x (to {amount})"] = partial(state.complete_bet_or_raise_to, amount)
        moves[f"all-in (to {max_to})"] = partial(state.complete_bet_or_raise_to, max_to)
    return moves


def jev_move(client, state, seat):
    """Play Jev's move and return (move, input_tokens, strength_seconds, api_seconds)."""
    moves = legal_moves(state)
    start = time.perf_counter()
    strength = hand_strength(state, seat)
    strength_done = time.perf_counter()
    question = Choice(instructions=instructions(strength), criteria=dict.fromkeys(moves))
    response = client.system_one(state=describe(state, seat), questions={"move": question})
    api_done = time.perf_counter()
    choice = response.choices["move"].choice
    moves[choice]()
    return choice, response.usage.input_tokens, strength_done - start, api_done - strength_done


def short(cards):
    return " ".join(map(repr, cards))


def main():
    load_dotenv()
    hands = []
    decisions = []
    total = 0
    opponent_seconds = 0
    start = time.perf_counter()
    with TypeSafeClient() as client:
        for hand_number in range(1, HANDS + 1):
            seat = hand_number % 2
            state = new_hand()
            names = {seat: "Jev", 1 - seat: opponent.SHORT_NAME}
            print(
                f"\nHand {hand_number} (Jev: {short(state.hole_cards[seat])}, "
                f"{opponent.SHORT_NAME}: {short(state.hole_cards[1 - seat])})"
            )
            street = None
            line = []
            while state.status:
                if STREETS[state.street_index] != street:
                    if line:
                        print("    " + " | ".join(line))
                        line = []
                    street = STREETS[state.street_index]
                    board = short(state.get_board_cards(0))
                    print(f"  {street} [{board}]:" if board else f"  {street}:")
                actor = state.actor_index
                if actor == seat:
                    move, *details = jev_move(client, state, seat)
                    decisions.append((hand_number, street, move, *details))
                else:
                    opponent_start = time.perf_counter()
                    move = opponent.play(state)
                    opponent_seconds += time.perf_counter() - opponent_start
                line.append(f"{names[actor]}: {move}")
            print("    " + " | ".join(line))
            won = state.stacks[seat] - STARTING_STACK
            total += won
            hands.append((seat, street, won))
            print(f"  Jev {won:+} chips (total {total:+})")
    elapsed = time.perf_counter() - start
    minutes, seconds = divmod(round(elapsed), 60)

    timings = {"seconds": elapsed, "opponent_seconds": opponent_seconds}
    batch_id, stats = save_batch(
        JEV_VERSION, JEV_VERSIONS[JEV_VERSION], opponent.NAME, hands, decisions, timings
    )
    print(f"\nBatch {batch_id} saved (Jev {JEV_VERSION} vs {opponent.NAME}):")
    for name, value in stats.items():
        print(f"  {name}: {value:.1f}" if isinstance(value, float) else f"  {name}: {value}")
    print(f"  time: {minutes}m {seconds}s")


if __name__ == "__main__":
    main()
