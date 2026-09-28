import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typesafe_sdk import TypeSafeClient

from game import BLINDS, bet_or_raise, pot_size_to
from hand import Hand

PAGE = Path(__file__).with_name("static") / "index.html"
SLIDER_PRESETS = {"1/3 Pot": 1 / 3, "1/2 Pot": 1 / 2, "3/4 Pot": 3 / 4, "Pot": 1}

load_dotenv()
client = TypeSafeClient()


@asynccontextmanager
async def lifespan(app):
    with client:
        yield


app = FastAPI(title="Jev Poker", lifespan=lifespan)


class Session:
    def __init__(self):
        self.hand = None
        self.hands_played = 0
        self.total = 0  # the visitor's chips won or lost over all hands


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
    let_jev_play(session)
    return view(session)
