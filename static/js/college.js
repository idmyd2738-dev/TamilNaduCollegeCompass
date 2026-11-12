const STORAGE_KEYS = {
  favorites: "collegehubFavorites",
  comparison: "collegehubComparison",
  searches: "collegehubSearches",
  conversations: "collegehubConversations"
};

const adminPage = document.querySelector('.admin-page[data-readonly="true"]');
if (adminPage) {
  adminPage.querySelectorAll("form:not([action='/admin/logout']) button, form:not([action='/admin/logout']) input, form:not([action='/admin/logout']) select, form:not([action='/admin/logout']) textarea")
    .forEach(control => { control.disabled = true; });
}

function showStorageMessage(message) {
  let status = document.getElementById("storageMessage");
  if (!status) {
    status = document.createElement("p");
    status.id = "storageMessage";
    status.className = "storage-message";
    status.setAttribute("role", "status");
    document.querySelector("main")?.prepend(status);
  }
  status.textContent = message;
}

function readList(key) {
  const raw = localStorage.getItem(key);
  if (!raw) return [];
  const value = JSON.parse(raw);
  if (!Array.isArray(value)) throw new TypeError(`Expected an array in local storage key ${key}`);
  return value;
}

function writeList(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
    return true;
  } catch (error) {
    console.error(`Unable to save ${key} in this browser.`, error);
    showStorageMessage("Browser storage is unavailable. Your changes were not saved.");
    return false;
  }
}

function updateCollegeActions() {
  const favorites = readList(STORAGE_KEYS.favorites).map(String);
  const comparison = readList(STORAGE_KEYS.comparison).map(String);
  document.querySelectorAll("[data-favorite-id]").forEach(button => {
    const saved = favorites.includes(button.dataset.favoriteId);
    button.setAttribute("aria-pressed", String(saved));
    button.textContent = saved ? "♥ Saved" : "♡ Save";
  });
  document.querySelectorAll("[data-compare-id]").forEach(button => {
    button.textContent = comparison.includes(button.dataset.compareId) ? "Added" : "Compare";
  });
  const count = document.getElementById("compareCount");
  if (count) count.textContent = String(comparison.length);
  const shortcut = document.querySelector(".compare-shortcut");
  if (shortcut) shortcut.href = comparison.length ? `/compare?ids=${comparison.join(",")}` : "/compare";
}

document.querySelectorAll("[data-favorite-id]").forEach(button => {
  button.addEventListener("click", () => {
    const favorites = readList(STORAGE_KEYS.favorites).map(String);
    const id = button.dataset.favoriteId;
    const updated = favorites.includes(id) ? favorites.filter(value => value !== id) : [...favorites, id];
    if (writeList(STORAGE_KEYS.favorites, updated)) updateCollegeActions();
  });
});

document.querySelectorAll("[data-compare-id]").forEach(button => {
  button.addEventListener("click", () => {
    const comparison = readList(STORAGE_KEYS.comparison).map(String);
    const id = button.dataset.compareId;
    let updated;
    if (comparison.includes(id)) {
      updated = comparison.filter(value => value !== id);
    } else if (comparison.length < 3) {
      updated = [...comparison, id];
    } else {
      showStorageMessage("Compare up to three colleges. Remove one before adding another.");
      return;
    }
    if (writeList(STORAGE_KEYS.comparison, updated)) updateCollegeActions();
  });
});

document.querySelectorAll("[data-remove-compare]").forEach(button => {
  button.addEventListener("click", () => {
    const updated = readList(STORAGE_KEYS.comparison).map(String)
      .filter(id => id !== button.dataset.removeCompare);
    if (writeList(STORAGE_KEYS.comparison, updated)) {
      window.location.href = updated.length ? `/compare?ids=${updated.join(",")}` : "/compare";
    }
  });
});

document.querySelectorAll(".tab-list [data-tab-target]").forEach(button => {
  button.addEventListener("click", () => {
    const target = document.getElementById(button.dataset.tabTarget);
    if (!target) return;
    const tabList = button.closest(".tab-list");
    tabList.querySelectorAll("[data-tab-target]").forEach(tab => {
      const active = tab === button;
      tab.classList.toggle("active", active);
      tab.setAttribute("aria-selected", String(active));
    });
    document.querySelectorAll(".tab-panel").forEach(panel => {
      const active = panel === target;
      panel.hidden = !active;
      panel.classList.toggle("active", active);
    });
  });
});

document.querySelectorAll("[data-password-toggle]").forEach(button => {
  button.addEventListener("click", () => {
    const input = button.parentElement.querySelector("input");
    const reveal = input.type === "password";
    input.type = reveal ? "text" : "password";
    button.textContent = reveal ? "Hide" : "Show";
  });
});

document.getElementById("collegeSearchForm")?.addEventListener("submit", event => {
  const params = new URLSearchParams(new FormData(event.currentTarget));
  params.delete("page");
  const search = params.toString();
  if (!search) return;
  const searches = readList(STORAGE_KEYS.searches).filter(value => value.url !== `/colleges?${search}`);
  searches.unshift({url: `/colleges?${search}`, label: params.get("q") || params.get("stream") || "College filters"});
  writeList(STORAGE_KEYS.searches, searches.slice(0, 8));
});

function appendSavedLink(container, label, href) {
  const link = document.createElement("a");
  link.href = href;
  link.textContent = label;
  container.append(link);
}

const collegeDirectory = window.collegeDirectory || [];
const savedColleges = document.getElementById("savedCollegeList");
if (savedColleges) {
  savedColleges.replaceChildren();
  const ids = readList(STORAGE_KEYS.favorites).map(Number);
  const found = collegeDirectory.filter(college => ids.includes(college.id));
  if (!found.length) savedColleges.textContent = "No saved colleges yet.";
  found.forEach(college => appendSavedLink(
    savedColleges, `${college.name} · ${college.district}`, `/colleges/${college.id}`
  ));
}

const savedSearches = document.getElementById("savedSearchList");
if (savedSearches) {
  savedSearches.replaceChildren();
  const searches = readList(STORAGE_KEYS.searches);
  if (!searches.length) savedSearches.textContent = "No saved searches yet. Searches are saved when you apply filters.";
  searches.forEach(search => appendSavedLink(savedSearches, search.label, search.url));
}

const savedConversations = document.getElementById("savedConversationList");
if (savedConversations) {
  savedConversations.replaceChildren();
  const conversations = readList(STORAGE_KEYS.conversations);
  if (!conversations.length) savedConversations.textContent = "No saved conversations yet.";
  conversations.slice().reverse().forEach(conversation =>
    appendSavedLink(savedConversations, conversation.title || "CollegeHub chat", "/chat")
  );
}

updateCollegeActions();
