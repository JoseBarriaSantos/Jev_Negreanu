import logging
import time
import uuid
from contextlib import asynccontextmanager, closing
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typesafe_sdk import TypeSafeClient

import jev
import stats
from game import BLINDS, bet_or_raise, pot_size_to
from hand import Hand

PAGE = Path(__file__).with_name("static") / "index.html"
SLIDER_PRESETS = {"1/3 Pot": 1 / 3, "1/2 Pot": 1 / 2, "3/4 Pot": 3 / 4, "Pot": 1}
OPPONENT = "Human"

load_dotenv()
client = TypeSafeClient()


@asynccontextmanager
async def lifespan(app):
    with client:
        yield


app = FastAPI(title="Jev Negreanu", lifespan=lifespan)


class Session:
    """One visitor's game. Their visit is saved as a batch with "Human" as the opponent."""

    def __init__(self):
        self.hand = None
        self.hands_played = 0
        self.total = 0  # the visitor's chips won or lost over all hands
        self.started_at = datetime.now()
        self.start_clock = time.perf_counter()
        self.batch_id = None  # created when the first hand finishes
        self.hands = []  # (jev_seat, ended_street, jev_net_chips) for the batch stats
        self.decisions = []  # Jev's (hand_number, street, move, tokens, strength_s, api_s)
        self.thinking_seconds = 0  # time the visitor spent deciding their moves
        self.turn_started = None


class Move(BaseModel):
    move: str | None = None  # "fold", "check", "call 4" or a preset like "bet 1/2 pot (to 18)"
    amount: int | None = None  # or bet/raise to any amount, from the slider


sessions = {}


def get_session(request: Request, response: Response):
    """Find the visitor's game from their cookie, or start a new one."""
    session_id = request.cookies.get("session")
    if session_id not in sessions:
        session_id = uuid.uuid4().hex
        sessions[session_id] = Session()
        response.set_cookie("session", session_id, httponly=True, samesite="lax")
    return sessions[session_id]


def let_jev_play(session):
    """Jev moves until it's the visitor's turn or the hand is over."""
    hand = session.hand
    while hand.jev_to_act:
        hand.play_jev()
    if hand.over:
        session.total -= hand.jev_won
        save_hand(session)
    else:
        session.turn_started = time.perf_counter()


def save_hand(session):
    """Add the finished hand to the visit's batch and refresh its summary.

    Stats are from Jev's side, like the batches against bots. A database error is
    logged instead of raised, so it never interrupts the game.
    """
    hand, number = session.hand, session.hands_played
    row = (hand.jev_seat, hand.ended_street, hand.jev_won)
    decisions = [(number, *decision) for decision in hand.decisions]
    session.hands.append(row)
    session.decisions.extend(decisions)
    timings = {
        "seconds": time.perf_counter() - session.start_clock,
        "opponent_seconds": session.thinking_seconds,
    }
    try:
        with closing(stats.connect()) as connection, connection:
            if session.batch_id is None:
                session.batch_id = stats.start_batch(
                    connection, jev.VERSION, jev.VERSIONS[jev.VERSION], OPPONENT, session.started_at
                )
            stats.add_hand(connection, session.batch_id, number, row, decisions)
            stats.update_summary(connection, session.batch_id, session.hands, session.decisions, timings)
    except Exception:
        logging.exception("Couldn't save the hand's stats")


def cards(cards):
    return [repr(card) for card in cards]


def controls(state):
    """What the visitor's buttons and bet slider can do right now.

    Preset amounts can fall outside min–max; the page greys those buttons out.
    """
    betting = None
    if state.can_complete_bet_or_raise_to():
        betting = {
            "verb": bet_or_raise(state),
            "min": state.min_completion_betting_or_raising_to_amount,
            "max": state.max_completion_betting_or_raising_to_amount,
            "step": BLINDS[1],
            "presets": {label: pot_size_to(state, share) for label, share in SLIDER_PRESETS.items()},
        }
    return {"can_fold": state.can_fold(), "call": state.checking_or_calling_amount, "bet": betting}


def view(session):
    """Everything the page needs to draw the table, from the visitor's side.

    Jev's cards are only shown when the hand ends without anyone folding.
    """
    hand = session.hand
    if hand is None:
        return {"hand_number": 0, "total": session.total}
    state = hand.state
    you, jev = 1 - hand.jev_seat, hand.jev_seat
    showdown = hand.over and hand.actions[-1][2] != "fold"
    return {
        "hand_number": session.hands_played,
        # With two players, PokerKit makes seat 1 the dealer, who posts the small blind.
        "you_are_dealer": you == 1,
        "your_cards": cards(hand.hole_cards[you]),
        "jev_cards": cards(hand.hole_cards[jev]) if showdown else None,
        "board": cards(state.get_board_cards(0)),
        "pot": state.total_pot_amount,
        "your_chips": state.stacks[you],
        "jev_chips": state.stacks[jev],
        "your_bet": state.bets[you],
        "jev_bet": state.bets[jev],
        "actions": [
            {"player": "Jev" if seat == jev else "You", "street": street, "move": move, "chips": chips}
            for seat, street, move, chips in hand.actions
        ],
        "controls": None if hand.over else controls(state),
        "over": hand.over,
        "result": -hand.jev_won if hand.over else None,
        "total": session.total,
    }


@app.get("/")
def home():
    return FileResponse(PAGE)


@app.get("/api/state")
def get_state(request: Request, response: Response):
    return view(get_session(request, response))


@app.post("/api/new-hand")
def new_hand(request: Request, response: Response):
    session = get_session(request, response)
    if session.hand and not session.hand.over:
        raise HTTPException(409, "Finish the current hand first.")
    session.hands_played += 1
    session.hand = Hand(client, jev_seat=session.hands_played % 2)
    let_jev_play(session)
    return view(session)


@app.post("/api/move")
def move(body: Move, request: Request, response: Response):
    session = get_session(request, response)
    hand = session.hand
    if hand is None or hand.over:
        raise HTTPException(409, "No hand in progress. Start a new hand.")
    if body.amount is not None:
        if not hand.state.can_complete_bet_or_raise_to(body.amount):
            raise HTTPException(400, f"You can't bet or raise to {body.amount} right now.")
        hand.play_bet_to(body.amount)
    elif body.move in hand.move_names():
        hand.play_move(body.move)
    else:
        raise HTTPException(400, f"That move isn't allowed right now. Options: {hand.move_names()}")
    session.thinking_seconds += time.perf_counter() - session.turn_started
    let_jev_play(session)
    return view(session)
