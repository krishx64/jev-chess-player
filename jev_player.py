"""Jev player for chess: pure Choice-over-legal-moves.

Skill: typesafe-ai (.agents/skills/typesafe-ai/SKILL.md)
Pattern: "Select instead of generate" - code enumerates legal moves,
Jev picks one via a Choice question. Legality, checkmate, stalemate
all stay in code (python-chess). Jev never generates free text moves.
"""

from __future__ import annotations

import chess
from typesafe_sdk import Choice, TypeSafeClient

PIECE_NAMES = {
    chess.PAWN: "pawn",
    chess.KNIGHT: "knight",
    chess.BISHOP: "bishop",
    chess.ROOK: "rook",
    chess.QUEEN: "queen",
    chess.KING: "king",
}


def describe_move(board: chess.Board, move: chess.Move) -> str:
    """Human-readable description for a legal move (goes into criteria)."""
    san = board.san(move)
    piece = board.piece_at(move.from_square)
    piece_name = PIECE_NAMES.get(piece.piece_type, "?") if piece else "?"
    uci = move.uci()
    tags: list[str] = []
    if board.is_capture(move):
        tags.append("capture")
        if board.is_en_passant(move):
            tags.append("en-passant")
    else:
        tags.append("quiet")
    if move.promotion:
        tags.append(f"promotes-to={chess.piece_name(move.promotion)}")
    if board.is_castling(move):
        tags.append("castling")
    # gives_check needs push/pop to be safe across versions
    board.push(move)
    gives_check = board.is_check()
    is_mate = board.is_checkmate()
    board.pop()
    if is_mate:
        tags.append("delivers-checkmate")
    elif gives_check:
        tags.append("gives-check")
    return f"{san} ({uci}, {piece_name} {chess.square_name(move.from_square)}->{chess.square_name(move.to_square)}, {', '.join(tags)})"


def material_count(board: chess.Board) -> dict:
    counts = {"white": {}, "black": {}}
    for color, label in ((chess.WHITE, "white"), (chess.BLACK, "black")):
        for pt in (chess.PAWN, chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN, chess.KING):
            n = len(board.pieces(pt, color))
            if n:
                counts[label][chess.piece_name(pt)] = n
    return counts


def build_state(board: chess.Board, history_sans: list[str]) -> dict:
    side = "white" if board.turn == chess.WHITE else "black"
    return {
        "position": {
            "fen": board.fen(),
            "side_to_move": side,
            "is_check": board.is_check(),
            "move_number": board.fullmove_number,
            "board_ascii": str(board),
            "material": material_count(board),
        },
        "history": history_sans[-12:],  # last 12 ply, enough context, bounded tokens
    }


def build_questions(board: chess.Board, style: str = "fun") -> dict:
    side = "white" if board.turn == chess.WHITE else "black"
    criteria = {m.uci(): describe_move(board, m) for m in board.legal_moves}
    style_hint = {
        "fun": "Keep winning as the priority; among comparably strong moves, prefer active and entertaining play.",
        "solid": "Keep winning as the priority; favor sound moves, development, king safety, and material.",
        "wild": "Keep winning as the priority; seek aggressive tactics when sound, and avoid sacrifices without compensation.",
    }.get(style, "Keep winning as the priority and choose the move that best improves this side's chances of victory.")
    return {
        "move": Choice(
            instructions={
                "question": f"Which legal move should {side} play to maximize its chances of winning?",
                "focus": style_hint,
                "playing_strength": "Play with the judgment of a professional chess player. Evaluate the full current `position` and `history`, and consider the opponent's strongest likely reply.",
                "long_term_plan": "Think beyond the immediate move. Prefer sound plans that improve piece activity, king safety, pawn structure, and the overall position.",
                "captures_and_exchanges": "Do not capture or exchange pieces automatically. Capture when it is tactically necessary or improves the position; do not avoid a clearly winning capture just to keep pieces on the board.",
                "tactical_priority": "Choose forced checkmate or a decisive tactical win when available. Otherwise choose the strongest sound move and limit the opponent's counterplay.",
                "play_as": side,
                "note": "Choose only from the given options. Each option is a legal move.",
            },
            criteria=criteria,
        )
    }


def choose_jev_move(
    board: chess.Board,
    client: TypeSafeClient,
    history_sans: list[str],
    style: str = "fun",
) -> dict:
    """Ask Jev for a move. Returns {uci, san, choice, confidence, probabilities}."""
    legal_uci = {m.uci() for m in board.legal_moves}
    if not legal_uci:
        raise ValueError("No legal moves - game is over.")
    # Choice supports up to 255 options; chess legal moves are ~<100.
    state = build_state(board, history_sans)
    questions = build_questions(board, style=style)
    result = client.system_one(state=state, questions=questions)

    # SDK exposes typed .choices plus raw .answers; support both.
    try:
        ans = result.choices["move"]
        choice, conf = ans.choice, float(ans.confidence)
        probs = dict(ans.probabilities or {})
    except Exception:
        ans = result.answers["move"]
        choice = ans["choice"] if isinstance(ans, dict) else ans.choice
        conf = float(ans["confidence"] if isinstance(ans, dict) else ans.confidence)
        raw_probs = ans["probabilities"] if isinstance(ans, dict) else ans.probabilities
        probs = dict(raw_probs or {})

    # Safety net: code owns legality. If Jev ever returns junk, fall back.
    if choice not in legal_uci:
        # try best-probability legal option before random
        ranked = sorted(probs.items(), key=lambda kv: -kv[1])
        choice = next((uci for uci, _ in ranked if uci in legal_uci), None)
    if choice not in legal_uci:
        import random

        choice = random.choice(sorted(legal_uci))
        conf = 0.0
    san = board.san(chess.Move.from_uci(choice))
    return {
        "uci": choice,
        "san": san,
        "confidence": conf,
        "probabilities": probs,
    }
