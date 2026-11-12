const form = document.getElementById("chatForm");
const input = document.getElementById("chatInput");
const messages = document.getElementById("chatMessages");
const welcome = document.getElementById("chatWelcome");
const conversationList = document.getElementById("conversationList");
const chatApp = document.getElementById("chatApp");
const conversations = [];
let nextConversationId = 1;
let activeConversation = {id: nextConversationId++, title: "New chat", messages: []};

function renderMessages() {
  messages.replaceChildren();
  welcome.hidden = activeConversation.messages.length > 0;
  for (const message of activeConversation.messages) {
    const row = document.createElement("div");
    row.className = `message ${message.who}`;
    const avatar = document.createElement("span");
    avatar.className = "message-avatar";
    avatar.textContent = message.who === "user" ? "You" : "C";
    const box = document.createElement("div");
    const label = document.createElement("small");
    label.textContent = message.who === "user" ? "YOU" : "COLLEGEHUB";
    const text = document.createElement("p");
    text.textContent = message.text;
    box.append(label, text);
    row.append(avatar, box);
    messages.append(row);
  }
  messages.scrollTop = messages.scrollHeight;
}

function renderConversationList() {
  conversationList.replaceChildren();
  for (const conversation of [...conversations].reverse()) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "conversation-item";
    button.classList.toggle("active", conversation.id === activeConversation.id);
    button.textContent = conversation.title;
    button.addEventListener("click", () => {
      activeConversation = conversation;
      renderMessages();
      renderConversationList();
      closeSidebar();
    });
    conversationList.append(button);
  }
}

function addMessage(conversation, text, who) {
  conversation.messages.push({text, who});
  if (conversation.id === activeConversation.id) renderMessages();
}

async function send(text) {
  const value = (text || input.value).trim();
  if (!value) return;

  const conversation = activeConversation;
  if (!conversations.includes(conversation)) conversations.push(conversation);
  if (conversation.messages.length === 0) {
    conversation.title = value.length > 34 ? `${value.slice(0, 34)}…` : value;
  }
  addMessage(conversation, value, "user");
  renderConversationList();
  input.value = "";
  input.focus();

  try {
    const response = await fetch("/demo-chat", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({message: value})
    });
    if (!response.ok) throw new Error(`Chat request failed with status ${response.status}`);
    const data = await response.json();
    addMessage(conversation, data.answer, "assistant");
  } catch {
    addMessage(conversation, "The demo assistant is temporarily unavailable. Please try again.", "assistant");
  }
}

function closeSidebar() {
  chatApp.classList.remove("sidebar-open");
}

form?.addEventListener("submit", event => {
  event.preventDefault();
  send();
});

document.querySelectorAll(".suggestions button").forEach(button =>
  button.addEventListener("click", () => send(button.textContent))
);

document.getElementById("newChatButton")?.addEventListener("click", () => {
  activeConversation = {id: nextConversationId++, title: "New chat", messages: []};
  renderMessages();
  renderConversationList();
  closeSidebar();
  input.focus();
});

document.getElementById("historyToggle")?.addEventListener("click", () => {
  chatApp.classList.add("sidebar-open");
});

document.getElementById("sidebarClose")?.addEventListener("click", closeSidebar);
document.getElementById("chatBackdrop")?.addEventListener("click", closeSidebar);
document.addEventListener("keydown", event => {
  if (event.key === "Escape") closeSidebar();
});

renderMessages();
renderConversationList();
