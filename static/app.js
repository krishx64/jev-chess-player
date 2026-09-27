"use strict";

const boardEl = document.getElementById("board");
const statusEl = document.getElementById("status");
const jevBox = document.getElementById("jevBox");
const movesTable = document.getElementById("movesTable");
const fenEl = document.getElementById("fen");
const toast = document.getElementById("toast");
const fileNames = "abcdefgh";
const glyphs = { k: "♚", q: "♛", r: "♜", b: "♝", n: "♞", p: "♟", K: "♔", Q: "♕", R: "♖", B: "♗", N: "♘", P: "♙" };

let state = null;
let selectedSquare = null;
let lastMove = null;
let flipped = false;
let autoPlay = false;
let busy = false;
let toastTimer = null;

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[char]);
}

function showToast(message) {
  toast.textContent = message;
  toast.style.display = "block";
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { toast.style.display = "none"; }, 4000);
}

async function api(path, body) {
  const response = await fetch(path, {
    method: body === undefined ? "GET" : "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await response.json().catch(() => ({ detail: response.statusText }));
  if (!response.ok) throw new Error(data.detail || `Request failed (${response.status})`);
  return data;
}

function piecesFromFen(fen) {
  const pieces = {};
  const rows = fen.split(" ")[0].split("/");
  rows.forEach((row, rowIndex) => {
    let file = 0;
    for (const char of row) {
      if (/\d/.test(char)) file += Number(char);
      else {
        pieces[`${fileNames[file]}${8 - rowIndex}`] = char;
        file += 1;
      }
    }
  });
  return pieces;
}

function squaresInDisplayOrder() {
  const squares = [];
  for (let rank = 8; rank >= 1; rank -= 1) {
    for (let file = 0; file < 8; file += 1) squares.push(`${fileNames[file]}${rank}`);
  }
  return flipped ? squares.reverse() : squares;
}

function isLightSquare(square) {
  return (fileNames.indexOf(square[0]) + Number(square[1])) % 2 === 0;
}

function setBusy(value, label = "") {
  busy = value;
  boardEl.setAttribute("aria-busy", String(value));
  document.getElementById("newBtn").disabled = value;
  document.getElementById("undoBtn").disabled = value || !state?.history_sans.length;
  document.getElementById("whiteSel").disabled = value;
  document.getElementById("blackSel").disabled = value;
  document.getElementById("styleSel").disabled = value;
  document.getElementById("autoBtn").disabled = value && !autoPlay;
  syncAutoButton();
  if (state) render(label);
}

function syncAutoButton() {
  const bothJev = state?.config.white === "jev" && state?.config.black === "jev";
  const button = document.getElementById("autoBtn");
  if (autoPlay) button.textContent = "⏸ Stop autoplay";
  else if (state?.turn_type === "jev") button.textContent = bothJev ? "▶ Resume Jev vs Jev" : "↻ Retry Jev move";
  else button.textContent = "▶ Watch Jev vs Jev";
}

function render(busyLabel = "") {
  if (!state) return;
  const pieces = piecesFromFen(state.fen);
  const legalFrom = new Map();
  for (const move of state.legal_moves) {
    if (!legalFrom.has(move.from)) legalFrom.set(move.from, []);
    legalFrom.get(move.from).push(move);
  }

  const isHumanTurn = state.turn_type === "human" && !state.is_game_over && !busy;
  const fragment = document.createDocumentFragment();
  for (const square of squaresInDisplayOrder()) {
    const squareEl = document.createElement("button");
    squareEl.type = "button";
    squareEl.className = `sq ${isLightSquare(square) ? "light" : "dark"}`;
    squareEl.dataset.square = square;
    squareEl.setAttribute("aria-label", `${square}${pieces[square] ? ` ${pieces[square]}` : ""}`);
    squareEl.tabIndex = 0;
    if (square === selectedSquare) squareEl.classList.add("sel");
    if (lastMove && (square === lastMove.slice(0, 2) || square === lastMove.slice(2, 4))) {
      squareEl.classList.add("last");
    }

    const piece = pieces[square];
    if (piece) {
      const pieceEl = document.createElement("span");
      pieceEl.className = `piece ${piece === piece.toUpperCase() ? "pc-w" : "pc-b"}`;
      pieceEl.textContent = glyphs[piece];
      squareEl.appendChild(pieceEl);
      const isCheckedKing = state.is_check && ((state.turn === "white" && piece === "K") || (state.turn === "black" && piece === "k"));
      if (isCheckedKing) squareEl.classList.add("check");
    }

    const destinations = selectedSquare ? legalFrom.get(selectedSquare) || [] : [];
    if (isHumanTurn && destinations.some((move) => move.to === square)) {
      const marker = document.createElement("span");
      marker.className = pieces[square] ? "cap" : "dot";
      squareEl.appendChild(marker);
    }

    const file = fileNames.indexOf(square[0]);
    const bottomRank = flipped ? "8" : "1";
    const leftFile = flipped ? 7 : 0;
    if (square[1] === bottomRank) {
      const coord = document.createElement("span");
      coord.className = "coord f";
      coord.textContent = square[0];
      squareEl.appendChild(coord);
    }
    if (file === leftFile) {
      const coord = document.createElement("span");
      coord.className = "coord r";
      coord.textContent = square[1];
      squareEl.appendChild(coord);
    }

    squareEl.addEventListener("click", () => onSquareClick(square));
    fragment.appendChild(squareEl);
  }
  boardEl.replaceChildren(fragment);

  const side = state.turn === "white" ? "White" : "Black";
  let message = state.is_game_over
    ? `Game over · ${state.result} · ${state.outcome}`
    : `${side} to move · ${state.turn_type === "human" ? "Your turn" : "Jev to move"}${state.is_check ? " · Check" : ""}`;
  if (busy && busyLabel) message = busyLabel;
  statusEl.replaceChildren();
  statusEl.className = state.is_game_over ? "good" : (state.is_check ? "bad" : "");
  if (busy) {
    const spinner = document.createElement("span");
    spinner.className = "spinner";
    spinner.setAttribute("aria-hidden", "true");
    statusEl.append(spinner);
  }
  statusEl.append(document.createTextNode(message));

  if (state.last_jev?.uci) {
    const moveText = `Last Jev move: ${state.last_jev.san || ""} (${state.last_jev.uci})`;
    const confidence = Math.max(0, Math.min(1, Number(state.last_jev.confidence) || 0));
    const top = Object.entries(state.last_jev.probabilities || {})
      .sort((a, b) => b[1] - a[1]).slice(0, 3)
      .map(([uci, probability]) => `${uci} ${(probability * 100).toFixed(0)}%`).join(" · ");
    jevBox.innerHTML = `<strong>${escapeHtml(moveText)}</strong>` +
      (state.last_jev.fallback
        ? `<br><span style="color:#ef8277">${escapeHtml(state.last_jev.fallback)}</span>`
        : `<br>Choice confidence ${(confidence * 100).toFixed(0)}%` +
          `<div class="confbar"><div style="width:${confidence * 100}%"></div></div>` +
          (top ? `<div style="color:var(--muted);margin-top:5px">Top choices: ${escapeHtml(top)}</div>` : ""));
  } else {
    jevBox.textContent = state.has_api_key
      ? "Jev's move and Choice confidence will appear here."
      : "No API key detected. Human vs Human works; Jev needs TYPESAFE_API_KEY in .env.";
  }

  const history = state.history_sans;
  const rows = [];
  for (let index = 0; index < history.length; index += 2) {
    const row = document.createElement("tr");
    for (const value of [`${Math.floor(index / 2) + 1}.`, history[index] || "", history[index + 1] || ""]) {
      const cell = document.createElement("td");
      cell.textContent = value;
      row.appendChild(cell);
    }
    rows.push(row);
  }
  if (!rows.length) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 3;
    cell.textContent = "No moves yet";
    row.appendChild(cell);
    rows.push(row);
  }
  movesTable.replaceChildren(...rows);
  document.getElementById("moves").scrollTop = document.getElementById("moves").scrollHeight;
  fenEl.textContent = `FEN · ${state.fen}`;
  document.getElementById("whiteSel").value = state.config.white;
  document.getElementById("blackSel").value = state.config.black;
  document.getElementById("styleSel").value = state.config.style;
  document.getElementById("undoBtn").disabled = busy || !history.length;
  syncAutoButton();
}

async function refresh() {
  state = await api("/api/state");
  lastMove = state.last_move || null;
  render();
  return state;
}

function onSquareClick(square) {
  if (!state || busy || state.is_game_over || state.turn_type !== "human") return;
  const pieces = piecesFromFen(state.fen);
  const moves = selectedSquare ? (state.legal_moves.filter((move) => move.from === selectedSquare && move.to === square)) : [];
  if (moves.length) {
    if (moves.length > 1) showPromotionPicker(moves);
    else submitHumanMove(moves[0].uci);
    return;
  }

  const piece = pieces[square];
  const belongsToSide = piece && ((state.turn === "white") === (piece === piece.toUpperCase()));
  selectedSquare = belongsToSide ? (selectedSquare === square ? null : square) : null;
  render();
}

function showPromotionPicker(moves) {
  const card = document.getElementById("promoCard");
  const pieceGlyphs = { q: "♛", r: "♜", b: "♝", n: "♞" };
  const white = state.turn === "white";
  const buttons = moves.map((move) => {
    const button = document.createElement("button");
    const piece = move.uci.slice(4);
    button.type = "button";
    button.title = `Promote to ${piece}`;
    button.setAttribute("aria-label", `Promote to ${piece}`);
    button.textContent = white ? pieceGlyphs[piece].replace("♛", "♕").replace("♜", "♖").replace("♝", "♗").replace("♞", "♘") : pieceGlyphs[piece];
    button.style.color = white ? "#fff" : "#111";
    button.addEventListener("click", () => {
      document.getElementById("promo").style.display = "none";
      submitHumanMove(move.uci);
    });
    return button;
  });
  card.replaceChildren(...buttons);
  document.getElementById("promo").style.display = "flex";
}

async function submitHumanMove(uci) {
  selectedSquare = null;
  setBusy(true, "Submitting move…");
  try {
    state = await api("/api/human-move", { move: uci });
    lastMove = state.last_move || uci;
    render();
  } catch (error) {
    showToast(error.message);
  } finally {
    setBusy(false);
    if (state?.turn_type === "jev" && !state.is_game_over) {
      window.setTimeout(() => makeJevMove(), 250);
    }
  }
}

async function makeJevMove() {
  if (!state || busy || state.is_game_over || state.turn_type !== "jev") return;
  setBusy(true, "Jev is choosing a legal move…");
  try {
    state = await api("/api/jev-move", {});
    lastMove = state.last_move || state.last_jev?.uci || null;
    render();
  } catch (error) {
    autoPlay = false;
    showToast(error.message);
  } finally {
    setBusy(false);
  }

  if (autoPlay && state && !state.is_game_over && state.turn_type === "jev") {
    window.setTimeout(makeJevMove, 450);
  } else if (autoPlay && (!state || state.is_game_over || state.turn_type !== "jev")) {
    autoPlay = false;
    render();
  }
}

async function startNewGame() {
  const white = document.getElementById("whiteSel").value;
  const black = document.getElementById("blackSel").value;
  const style = document.getElementById("styleSel").value;
  setBusy(true, "Starting a new game…");
  try {
    state = await api("/api/new-game", { white, black, style });
    selectedSquare = null;
    lastMove = null;
    autoPlay = white === "jev" && black === "jev";
    render();
  } catch (error) {
    showToast(error.message);
  } finally {
    setBusy(false);
  }
  if (state?.turn_type === "jev" && !state.is_game_over) window.setTimeout(makeJevMove, 200);
}

document.getElementById("newBtn").addEventListener("click", startNewGame);
document.getElementById("flipBtn").addEventListener("click", () => { flipped = !flipped; render(); });
document.getElementById("undoBtn").addEventListener("click", async () => {
  if (busy) return;
  setBusy(true, "Undoing move…");
  try {
    state = await api("/api/undo", {});
    lastMove = state.last_move || null;
    selectedSquare = null;
    render();
  } catch (error) {
    showToast(error.message);
  } finally {
    setBusy(false);
  }
});
document.getElementById("autoBtn").addEventListener("click", async () => {
  if (autoPlay) {
    autoPlay = false;
    render();
    return;
  }
  if (state?.turn_type === "jev") {
    const bothJev = state.config.white === "jev" && state.config.black === "jev";
    autoPlay = bothJev;
    render();
    makeJevMove();
    return;
  }
  if (state?.config.white !== "jev" || state?.config.black !== "jev") {
    document.getElementById("whiteSel").value = "jev";
    document.getElementById("blackSel").value = "jev";
    await startNewGame();
    return;
  }
  autoPlay = true;
  render();
  makeJevMove();
});
document.getElementById("promo").addEventListener("click", (event) => {
  if (event.target.id === "promo") document.getElementById("promo").style.display = "none";
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    selectedSquare = null;
    document.getElementById("promo").style.display = "none";
    render();
  }
});

refresh().then(() => {
  if (state.config.white === "jev" && state.config.black === "jev") autoPlay = true;
  render();
  if (state.turn_type === "jev" && !state.is_game_over) window.setTimeout(makeJevMove, 200);
}).catch((error) => {
  statusEl.textContent = `Can't connect to the chess server. Start it with python app.py. ${error.message}`;
  statusEl.className = "bad";
});
