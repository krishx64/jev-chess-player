"""CLI: human vs Jev, Jev vs Jev (pure Jev Choice).

Rules (legal moves, check, checkmate, stalemate, draws) are 100% python-chess.
Jev only selects from the legal list built in code.

Usage:
  python play.py --white jev --black jev
  python play.py --white human --black jev
  python play.py --white jev --black human --style wild
  python play.py --white human --black human   # no API key needed

Env:
  TYPESAFE_API_KEY  required when any side is jev.
"""

from __future__ import annotations

import argparse
import os
import random
import sys
import time

import chess

try:
    from dotenv import load_dotenv

    load_dotenv()  # pick up .env (TYPESAFE_*) if present
except ImportError:
    pass

from jev_player import choose_jev_move


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Chess with Jev (pure Choice).")
    p.add_argument("--white", choices=["human", "jev"], default="human")
    p.add_argument("--black", choices=["human", "jev"], default="jev")
    p.add_argument("--style", choices=["fun", "solid", "wild"], default="fun",
                   help="Jev personality hint (white+black share it unless --black-style given).")
    p.add_argument("--black-style", default=None, help="Override style for black.")
    p.add_argument("--max-moves", type=int, default=200, help="Ply limit (default 200).")
    p.add_argument("--delay", type=float, default=0.5, help="Pause between Jev moves.")
    p.add_argument("--seed", type=int, default=None)
    return p.parse_args()


def human_move(board: chess.Board) -> chess.Move:
    legal = list(board.legal_moves)
    print(f"Legal ({len(legal)}): " + " ".join(sorted(board.san(m) for m in legal)))
    while True:
        raw = input("Your move (SAN or UCI, e.g. Nf3 / g1f3, or 'quit'): ").strip()
        if raw.lower() in {"quit", "exit", "resign"}:
            print("You resigned.")
            sys.exit(0)
        try:
            try:
                mv = board.parse_san(raw)
            except ValueError:
                mv = chess.Move.from_uci(raw)
            if mv in board.legal_moves:
                return mv
            print("Illegal move, try again.")
        except Exception:
            print("Could not parse, try again (e.g. e4, Nf3, e7e8q).")


def top_probs(probs: dict, k: int = 3) -> str:
    ranked = sorted(probs.items(), key=lambda kv: -kv[1])[:k]
    return ", ".join(f"{uci} {p:.2f}" for uci, p in ranked)


def main() -> None:
    args = parse_args()
    if args.seed is not None:
        random.seed(args.seed)
    needs_api = args.white == "jev" or args.black == "jev"
    if needs_api and not os.environ.get("TYPESAFE_API_KEY"):
        print("ERROR: TYPESAFE_API_KEY is not set (required for Jev moves).")
        print("Get one at https://console.typesafe.ai/ then:")
        print('  $env:TYPESAFE_API_KEY="ts-..."  (PowerShell)')
        sys.exit(2)

    from typesafe_sdk import TypeSafeClient

    board = chess.Board()
    history_sans: list[str] = []
    styles = {
        chess.WHITE: args.style,
        chess.BLACK: args.black_style or args.style,
    }
    sides = {chess.WHITE: args.white, chess.BLACK: args.black}

    client = TypeSafeClient() if needs_api else None
    try:
        ply = 0
        while not board.is_game_over() and ply < args.max_moves:
            print("\n" + str(board))
            print(f"FEN: {board.fen()}")
            turn = board.turn
            who = sides[turn]
            label = "White" if turn == chess.WHITE else "Black"
            if board.is_check():
                print(f"{label} is in CHECK.")
            if who == "human":
                mv = human_move(board)
                san = board.san(mv)
                board.push(mv)
                history_sans.append(san)
                print(f"{label} (human) played {san}")
            else:
                assert client is not None
                try:
                    res = choose_jev_move(board, client, history_sans, style=styles[turn])
                except Exception as e:
                    print(f"Jev call failed ({e}); playing random legal move.")
                    mv = random.choice(list(board.legal_moves))
                    san = board.san(mv)
                    board.push(mv)
                    history_sans.append(san)
                    ply += 1
                    continue
                mv = chess.Move.from_uci(res["uci"])
                board.push(mv)
                history_sans.append(res["san"])
                print(f"{label} (jev,{styles[turn]}) played {res['san']} "
                      f"[{res['uci']}] conf={res['confidence']:.2f} top={top_probs(res['probabilities'])}")
                time.sleep(args.delay)
            ply += 1

        print("\n" + str(board))
        print(f"Result: {board.result()}  over={board.is_game_over()}")
        if board.is_checkmate():
            winner = "Black" if board.turn == chess.WHITE else "White"
            print(f"Checkmate - {winner} wins.")
        elif board.is_stalemate():
            print("Stalemate - draw.")
        elif board.is_insufficient_material():
            print("Draw - insufficient material.")
        elif board.is_seventyfive_moves() or board.is_fivefold_repetition():
            print("Draw - automatic rule.")
        elif board.is_fifty_moves() or board.is_repetition(3):
            print("Draw - claimable (fifty-move / threefold).")
        elif ply >= args.max_moves:
            print("Stopped - max-moves reached.")
    finally:
        if client is not None:
            client.close()


if __name__ == "__main__":
    main()
