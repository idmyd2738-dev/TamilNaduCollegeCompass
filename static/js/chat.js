const form = document.getElementById("chatForm");
const input = document.getElementById("chatInput");
const messages = document.getElementById("chatMessages");
function addMessage(text, who) {
  const row = document.createElement("div");
  row.className = `message ${who}`;
  const avatar = document.createElement("span");
  avatar.className = "message-avatar";
  avatar.textContent = who === "user" ? "You" : "✳";
  const box = document.createElement("div");
  const label = document.createElement("small");
  label.textContent = who === "user" ? "YOU" : "COMPASS";
  const p = document.createElement("p");
  p.textContent = text;
  box.append(label, p); row.append(avatar, box); messages.append(row);
  messages.scrollTop = messages.scrollHeight;
}
async function send(text) {
  const value = (text || input.value).trim();
  if (!value) return;
  addMessage(value, "user"); input.value = "";
  try {
    const response = await fetch("/demo-chat", {
      method: "POST", headers: {"Content-Type":"application/json"},
      body: JSON.stringify({message:value})
    });
    const data = await response.json();
    addMessage(data.answer, "assistant");
  } catch {
    addMessage("The demo assistant is temporarily unavailable. Please try again.", "assistant");
  }
}
form?.addEventListener("submit", e => { e.preventDefault(); send(); });
document.querySelectorAll(".suggestions button").forEach(button =>
  button.addEventListener("click", () => send(button.textContent))
);
