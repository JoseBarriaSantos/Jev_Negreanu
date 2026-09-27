from functools import lru_cache

from pokerkit import Deck, StandardHighHand, calculate_hand_strength

SAMPLE_COUNT = 300


def hand_strength(state, seat):
    """Chance (0 to 1) that this seat's hand beats a random hand once all cards are dealt."""
    return _cached_strength(
        frozenset(state.hole_cards[seat]), frozenset(state.get_board_cards(0))
    )


@lru_cache(maxsize=100_000)
def _cached_strength(hole_cards, board_cards):
    """Remembers every answer, so the same cards and board are only worked out once.

    Card order doesn't change the answer, so the cards are passed as sets. That
    also means repeat starting hands before the flop reuse earlier results
    across the whole batch.
    """
    return calculate_hand_strength(
        2,
        [hole_cards],
        board_cards,
        2,
        5,
        Deck.STANDARD,
        (StandardHighHand,),
        sample_count=SAMPLE_COUNT,
    )
