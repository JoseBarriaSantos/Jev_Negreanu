import time

from typesafe_sdk import Choice

from game import STREETS, legal_moves
from strength import hand_strength

VERSION = "1.2"
VERSIONS = {
    "1.0": "Base version: sees its cards, the board, pot, chips and bets, and picks from the legal moves.",
    "1.1": "Hand strength (chance of beating a random hand) added to the instructions.",
    "1.2": "Pot-based sizes on every street: bets and raises of 1/3 pot to 1.5 pot (was multiples of the min raise).",
}


def instructions(strength):
    return (
        "You are playing heads-up No-Limit Texas Hold'em. "
        f"Your hand strength is {strength:.0%}: the chance your hand beats a random hand "
        "once all the cards are dealt. "
        "Pick the move that wins the most chips in the long run."
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


def play(client, state, seat):
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
