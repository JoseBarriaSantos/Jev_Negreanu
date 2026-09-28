import time

from dotenv import load_dotenv
from typesafe_sdk import TypeSafeClient

import jev
import straight_joe as opponent
from game import STREETS, short
from hand import Hand
from stats import save_batch

HANDS = 100


def print_hand(hand, number, total):
    names = {hand.jev_seat: "Jev", 1 - hand.jev_seat: opponent.SHORT_NAME}
    other_seat = 1 - hand.jev_seat
    print(
        f"\nHand {number} (Jev: {short(hand.hole_cards[hand.jev_seat])}, "
        f"{opponent.SHORT_NAME}: {short(hand.hole_cards[other_seat])})"
    )
    for street in STREETS:
        moves = [f"{names[seat]}: {move}" for seat, s, move, _ in hand.actions if s == street]
        if moves:
            board = short(hand.boards[street])
            print(f"  {street} [{board}]:" if board else f"  {street}:")
            print("    " + " | ".join(moves))
    print(f"  Jev {hand.jev_won:+} chips (total {total:+})")


def main():
    load_dotenv()
    hands = []
    decisions = []
    total = 0
    opponent_seconds = 0
    start = time.perf_counter()
    with TypeSafeClient() as client:
        for number in range(1, HANDS + 1):
            hand = Hand(client, jev_seat=number % 2)
            while not hand.over:
                if hand.jev_to_act:
                    hand.play_jev()
                else:
                    opponent_start = time.perf_counter()
                    hand.play_bot(opponent)
                    opponent_seconds += time.perf_counter() - opponent_start
            total += hand.jev_won
            hands.append((hand.jev_seat, hand.ended_street, hand.jev_won))
            decisions.extend((number, *decision) for decision in hand.decisions)
            print_hand(hand, number, total)
    elapsed = time.perf_counter() - start
    minutes, seconds = divmod(round(elapsed), 60)

    timings = {"seconds": elapsed, "opponent_seconds": opponent_seconds}
    batch_id, stats = save_batch(
        jev.VERSION, jev.VERSIONS[jev.VERSION], opponent.NAME, hands, decisions, timings
    )
    print(f"\nBatch {batch_id} saved (Jev {jev.VERSION} vs {opponent.NAME}):")
    for name, value in stats.items():
        print(f"  {name}: {value:.1f}" if isinstance(value, float) else f"  {name}: {value}")
    print(f"  time: {minutes}m {seconds}s")


if __name__ == "__main__":
    main()
