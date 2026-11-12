const form = document.getElementById("chatForm");
const input = document.getElementById("chatInput");
const messages = document.getElementById("chatMessages");
const welcome = document.getElementById("chatWelcome");
const conversationList = document.getElementById("conversationList");
const chatApp = document.getElementById("chatApp");
const conversationsKey = "collegehubConversations";
let conversations = [];
let nextConversationId = 1;

function showChatStorageMessage(message) {
  const status = document.createElement("p");
  status.className = "storage-message";
  status.setAttribute("role", "alert");
  status.textContent = message;
  document.querySelector(".composer-area")?.prepend(status);
}

function loadConversations() {
  try {
    const raw = localStorage.getItem(conversationsKey);
    const saved = raw ? JSON.parse(raw) : [];
    if (!Array.isArray(saved)) throw new TypeError("Conversation storage must contain a list.");
    return saved.filter(item => item && Array.isArray(item.messages));
  } catch (error) {
    console.error("Unable to read CollegeHub conversation history.", error);
    showChatStorageMessage("Conversation history could not be read from this browser.");
    return [];
  }
}

function saveConversations() {
  try {
    localStorage.setItem(conversationsKey, JSON.stringify(conversations));
  } catch (error) {
    console.error("Unable to save CollegeHub conversation history.", error);
    showChatStorageMessage("Conversation could not be saved in this browser.");
  }
}

function newConversation() {
  const conversation = {id: String(nextConversationId++), title: "New chat", messages: []};
  conversations.push(conversation);
  return conversation;
}

conversations = loadConversations();
if (conversations.length) {
  nextConversationId = conversations.reduce((max, item) => Math.max(max, Number(item.id) || 0), 0) + 1;
}
let activeConversation = newConversation();

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
    if (message.sourceName && message.sourceUrl) {
      try {
        const source = new URL(message.sourceUrl);
        if (source.protocol === "https:" || source.protocol === "http:") {
          const link = document.createElement("a");
          link.href = source.href;
          link.target = "_blank";
          link.rel = "noopener noreferrer";
          link.className = "message-source";
          link.textContent = `${message.sourceName} ↗`;
          box.append(link);
        }
      } catch (error) {
        console.error("Ignoring an invalid source URL from a saved conversation.", error);
      }
    }
    row.append(avatar, box);
    messages.append(row);
  }
  messages.scrollTop = messages.scrollHeight;
}

function renderConversationList() {
  conversationList.replaceChildren();
  for (const conversation of conversations.filter(item => item.messages.length).slice().reverse()) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "conversation-item";
    button.classList.toggle("active", conversation.id === activeConversation.id);
    button.textContent = conversation.title || "CollegeHub chat";
    button.addEventListener("click", () => {
      activeConversation = conversation;
      renderMessages();
      renderConversationList();
      closeSidebar();
    });
    conversationList.append(button);
  }
}

function addMessage(conversation, message) {
  conversation.messages.push(message);
  saveConversations();
  if (conversation.id === activeConversation.id) renderMessages();
  renderConversationList();
}

async function send(text) {
  const value = (text || input.value).trim();
  if (!value) return;
  const conversation = activeConversation;
  if (conversation.messages.length === 0) {
    conversation.title = value.length > 38 ? `${value.slice(0, 38)}…` : value;
  }
  addMessage(conversation, {text: value, who: "user"});
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
    addMessage(conversation, {
      text: data.answer,
      who: "assistant",
      sourceName: data.source_name,
      sourceUrl: data.source_url
    });
  } catch (error) {
    console.error("CollegeHub demo chat request failed.", error);
    addMessage(conversation, {
      text: "The demo assistant is temporarily unavailable. Please try again.",
      who: "assistant"
    });
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
  activeConversation = newConversation();
  renderMessages();
  renderConversationList();
  closeSidebar();
  input.focus();
});

document.getElementById("clearChatButton")?.addEventListener("click", () => {
  conversations = conversations.filter(item => item.id !== activeConversation.id);
  activeConversation = newConversation();
  saveConversations();
  renderMessages();
  renderConversationList();
  input.focus();
});

document.getElementById("historyToggle")?.addEventListener("click", () => chatApp.classList.add("sidebar-open"));
document.getElementById("sidebarClose")?.addEventListener("click", closeSidebar);
document.getElementById("chatBackdrop")?.addEventListener("click", closeSidebar);
document.addEventListener("keydown", event => {
  if (event.key === "Escape") closeSidebar();
});

renderMessages();
renderConversationList();
