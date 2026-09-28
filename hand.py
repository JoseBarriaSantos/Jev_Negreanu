import re

import jev
from game import STARTING_STACK, STREETS, bet_to_name, legal_moves, new_state


def chips_put_in(move, bet_before):
    """How many chips a move adds to the table, read from its name.

    "call 4" adds 4. Bets, raises and all-ins name the total they go "to", so
    "raise 2x (to 8)" after already betting 2 adds 6. Checks and folds add 0.
    """
    if match := re.search(r"to (\d+)", move):
        return int(match[1]) - bet_before
    if match := re.match(r"call (\d+)", move):
        return int(match[1])
    return 0


class Hand:
    """One hand between Jev and one other player, played a move at a time.

    Jev moves with play_jev() whenever jev_to_act is true. The other player is
    either a bot (play_bot) or a person picking a name from move_names()
    (play_move). The cards are copied when the hand starts, because PokerKit
    throws away folded and losing hands at the end.
    """

    def __init__(self, client, jev_seat):
        self.client = client
        self.jev_seat = jev_seat
        self.state = new_state()
        self.hole_cards = [list(cards) for cards in self.state.hole_cards]
        self.boards = {}  # street -> table cards on that street
        self.actions = []  # (seat, street, move, chips put in) in the order they happened
        self.decisions = []  # Jev's (street, move, input_tokens, strength_seconds, api_seconds)

    @property
    def over(self):
        return not self.state.status

    @property
    def jev_to_act(self):
        return not self.over and self.state.actor_index == self.jev_seat

    @property
    def ended_street(self):
        return self.actions[-1][1]

    @property
    def jev_won(self):
        return self.state.stacks[self.jev_seat] - STARTING_STACK

    def move_names(self):
        return list(legal_moves(self.state))

    def play_jev(self):
        seat, street, bet = self._start_move()
        move, *details = jev.play(self.client, self.state, seat)
        self.decisions.append((street, move, *details))
        self.actions.append((seat, street, move, chips_put_in(move, bet)))

    def play_move(self, name):
        seat, street, bet = self._start_move()
        legal_moves(self.state)[name]()
        self.actions.append((seat, street, name, chips_put_in(name, bet)))

    def play_bet_to(self, amount):
        """Bet or raise to any legal amount, not just the preset sizes."""
        seat, street, bet = self._start_move()
        name = bet_to_name(self.state, amount)
        self.state.complete_bet_or_raise_to(amount)
        self.actions.append((seat, street, name, chips_put_in(name, bet)))

    def play_bot(self, bot):
        seat, street, bet = self._start_move()
        move = bot.play(self.state)
        self.actions.append((seat, street, move, chips_put_in(move, bet)))

    def _start_move(self):
        seat = self.state.actor_index
        street = STREETS[self.state.street_index]
        self.boards.setdefault(street, list(self.state.get_board_cards(0)))
        return seat, street, self.state.bets[seat]
