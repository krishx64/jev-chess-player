"""Web UI backend: FastAPI + python-chess + Jev Choice.

Rules stay in code (python-chess). Jev only picks from legal moves
via jev_player.choose_jev_move (pure Choice).

Run:
  python app.py
  -> http://127.0.0.1:8000
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Optional

import chess
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

try:
    from dotenv import load_dotenv

    load_dotenv()  # pick up .env (TYPESAFE_*, PORT) if present
except ImportError:
    pass

from jev_player import choose_jev_move

BASE = Path(__file__).parent
app = FastAPI(title="Chess x Jev")

_lock = threading.Lock()
_board = chess.Board()
_history_sans: list[str] = []
_config = {"white": "human", "black": "jev", "style": "fun", "black_style": None}
_last_jev: dict = {}
_client = None  # lazy TypeSafeClient


def get_client():
    global _client
    if _client is None:
        if not os.environ.get("TYPESAFE_API_KEY"):
            raise HTTPException(
                status_code=428,
                detail="TYPESAFE_API_KEY is not set. Set it then restart the server.",
            )
        from typesafe_sdk import TypeSafeClient

        _client = TypeSafeClient()
    return _client


def outcome_text() -> str:
    b = _board
    if b.is_checkmate():
        winner = "Black" if b.turn == chess.WHITE else "White"
        return f"Checkmate — {winner} wins."
    if b.is_stalemate():
        return "Stalemate — draw."
    if b.is_insufficient_material():
        return "Draw — insufficient material."
    if b.is_seventyfive_moves() or b.is_fivefold_repetition():
        return "Draw — automatic rule."
    if b.is_fifty_moves() or b.is_repetition(3):
        return "Draw — claimable (fifty-move / threefold)."
    if b.is_check():
        return "Check."
    return ""


def legal_list() -> list[dict]:
    out = []
    for m in _board.legal_moves:
        out.append(
            {
                "uci": m.uci(),
                "san": _board.san(m),
                "from": chess.square_name(m.from_square),
                "to": chess.square_name(m.to_square),
                "promotion": chess.piece_name(m.promotion) if m.promotion else None,
            }
        )
    return out


def state_payload() -> dict:
    last_move = _board.move_stack[-1].uci() if _board.move_stack else None
    return {
        "fen": _board.fen(),
        "last_move": last_move,
        "turn": "white" if _board.turn == chess.WHITE else "black",
        "turn_type": _config["white"] if _board.turn == chess.WHITE else _config["black"],
        "is_check": _board.is_check(),
        "is_game_over": _board.is_game_over(),
        "result": _board.result() if _board.is_game_over() else "*",
        "outcome": outcome_text(),
        "history_sans": list(_history_sans),
        "legal_moves": legal_list(),
        "last_jev": _last_jev,
        "config": dict(_config),
        "has_api_key": bool(os.environ.get("TYPESAFE_API_KEY")),
    }


class NewGame(BaseModel):
    white: str = "human"
    black: str = "jev"
    style: str = "fun"
    black_style: Optional[str] = None


class HumanMove(BaseModel):
    move: str  # SAN or UCI


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")


@app.get("/app.js")
def app_script():
    return FileResponse(BASE / "static" / "app.js", media_type="text/javascript")


@app.get("/api/state")
def api_state():
    with _lock:
        return state_payload()


@app.post("/api/new-game")
def api_new_game(cfg: NewGame):
    if cfg.white not in ("human", "jev") or cfg.black not in ("human", "jev"):
        raise HTTPException(400, "white/black must be 'human' or 'jev'")
    with _lock:
        global _board, _history_sans, _last_jev
        _board = chess.Board()
        _history_sans = []
        _last_jev = {}
        _config.update(
            {"white": cfg.white, "black": cfg.black, "style": cfg.style,
             "black_style": cfg.black_style or cfg.style}
        )
        return state_payload()


@app.post("/api/human-move")
def api_human_move(m: HumanMove):
    with _lock:
        if _board.is_game_over():
            raise HTTPException(400, "Game is over. Start a new game.")
        expected = _config["white"] if _board.turn == chess.WHITE else _config["black"]
        if expected != "human":
            raise HTTPException(400, f"It is Jev's turn, not human's.")
        raw = m.move.strip()
        try:
            try:
                mv = _board.parse_san(raw)
            except ValueError:
                mv = chess.Move.from_uci(raw)
        except Exception:
            raise HTTPException(400, f"Could not parse move '{raw}'. Use SAN (Nf3) or UCI (g1f3).")
        if mv not in _board.legal_moves:
            raise HTTPException(400, "Illegal move.")
        san = _board.san(mv)
        _board.push(mv)
        _history_sans.append(san)
        return state_payload()


@app.post("/api/jev-move")
def api_jev_move():
    global _last_jev
    with _lock:
        if _board.is_game_over():
            raise HTTPException(400, "Game is over. Start a new game.")
        expected = _config["white"] if _board.turn == chess.WHITE else _config["black"]
        if expected != "jev":
            raise HTTPException(400, "It is human's turn, not Jev's.")
        style = _config["style"] if _board.turn == chess.WHITE else (_config["black_style"] or _config["style"])
        client = get_client()
        # Release no locks during network call is complex; keep lock (single-user local UI).
        try:
            res = choose_jev_move(_board, client, _history_sans, style=style)
        except HTTPException:
            raise
        except Exception as e:
            # A provider failure is not a Jev move. Keep the position unchanged so
            # the UI can show the error and let the user retry after fixing billing.
            raise HTTPException(status_code=502, detail=f"Jev request failed: {e}") from e
        mv = chess.Move.from_uci(res["uci"])
        _board.push(mv)
        _history_sans.append(res["san"])
        _last_jev = res
        return state_payload()


@app.post("/api/undo")
def api_undo():
    with _lock:
        global _last_jev
        for _ in range(2):
            if _board.move_stack:
                _board.pop()
                if _history_sans:
                    _history_sans.pop()
            else:
                break
        _last_jev = {}
        return state_payload()


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(app, host="127.0.0.1", port=port)
