from pokerkit import Deck, StandardHighHand, calculate_hand_strength

SAMPLE_COUNT = 1000


def hand_strength(state, seat):
    """Chance (0 to 1) that this seat's hand beats a random hand once all cards are dealt."""
    return calculate_hand_strength(
        2,
        [state.hole_cards[seat]],
        list(state.get_board_cards(0)),
        2,
        5,
        Deck.STANDARD,
        (StandardHighHand,),
        sample_count=SAMPLE_COUNT,
    )
