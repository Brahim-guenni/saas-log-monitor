document.querySelector(".nav-toggle")?.addEventListener("click", () => {
  document.querySelector(".navbar")?.classList.toggle("open");
});

const dropZone = document.getElementById("drop-zone");
const fileInput = document.getElementById("file-input");
let selectedFile = null;

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, char => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;"
  })[char]);
}

async function previewFile(file) {
  if (!file) return;
  selectedFile = file;
  const form = new FormData();
  form.append("file", file);
  const response = await fetch("/upload/preview", { method: "POST", body: form });
  const data = await response.json();
  if (!response.ok) {
    document.getElementById("preview").innerHTML =
      `<div class="alert alert-error">${escapeHtml(data.error)}</div>`;
    document.getElementById("confirm-upload").hidden = true;
    return;
  }

  const rows = data.preview || [];
  if (!rows.length) {
    document.getElementById("preview").innerHTML = "<p>Aucune ligne à afficher.</p>";
  } else {
    const headers = Object.keys(rows[0]);
    document.getElementById("preview").innerHTML =
      `<div class="table-wrap"><table><thead><tr>${headers.map(h => `<th>${escapeHtml(h)}</th>`).join("")}</tr></thead>` +
      `<tbody>${rows.slice(0, 10).map(row => `<tr>${headers.map(h => `<td>${escapeHtml(row[h])}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
  }
  document.getElementById("confirm-upload").hidden = false;
  document.getElementById("cancel-upload").hidden = false;
}

dropZone?.addEventListener("click", () => fileInput.click());
fileInput?.addEventListener("change", event => previewFile(event.target.files[0]));
["dragenter", "dragover"].forEach(name => dropZone?.addEventListener(name, event => {
  event.preventDefault();
  dropZone.classList.add("dragging");
}));
["dragleave", "drop"].forEach(name => dropZone?.addEventListener(name, event => {
  event.preventDefault();
  dropZone.classList.remove("dragging");
}));
dropZone?.addEventListener("drop", event => previewFile(event.dataTransfer.files[0]));

document.getElementById("cancel-upload")?.addEventListener("click", () => {
  selectedFile = null;
  fileInput.value = "";
  document.getElementById("preview").innerHTML = "";
  document.getElementById("confirm-upload").hidden = true;
  document.getElementById("cancel-upload").hidden = true;
});

document.getElementById("confirm-upload")?.addEventListener("click", async () => {
  if (!selectedFile) return;
  const form = new FormData();
  form.append("file", selectedFile);
  const progress = document.getElementById("upload-progress");
  const bar = progress.querySelector("div");
  progress.hidden = false;
  bar.style.width = "30%";

  const response = await fetch("/upload", { method: "POST", body: form });
  const data = await response.json();
  bar.style.width = response.ok ? "100%" : "0";
  if (!response.ok) {
    document.getElementById("preview").innerHTML =
      `<div class="alert alert-error">${escapeHtml(data.error)}</div>`;
    return;
  }
  document.getElementById("preview").innerHTML =
    `<div class="alert">${escapeHtml(data.message)} — ${escapeHtml(data.file.filename)}</div>`;
  document.getElementById("confirm-upload").hidden = true;
  setTimeout(() => window.location.reload(), 700);
});

const searchForm = document.getElementById("search-form");
let searchPage = 1;

async function runSearch(page = 1) {
  if (!searchForm) return;
  searchPage = page;
  const params = new URLSearchParams(new FormData(searchForm));
  params.set("page", String(page));
  params.set("size", "50");

  const dateFrom = params.get("date_from");
  const dateTo = params.get("date_to");
  if (dateFrom && dateTo && dateFrom > dateTo) {
    alert("La date de fin doit être postérieure à la date de début.");
    return;
  }

  document.getElementById("loading").hidden = false;
  const response = await fetch(`/api/v1/search?${params.toString()}`);
  const data = await response.json();
  document.getElementById("loading").hidden = true;
  if (!response.ok) {
    document.getElementById("results-body").innerHTML =
      `<tr><td colspan="5" class="alert-error">${escapeHtml(data.error)}</td></tr>`;
    return;
  }

  document.getElementById("results-count").textContent =
    `${data.total} résultat(s)`;
  document.getElementById("page-label").textContent =
    `Page ${data.page} / ${data.pages}`;
  document.getElementById("prev-page").disabled = data.page <= 1;
  document.getElementById("next-page").disabled = data.page >= data.pages;
  window.currentLogs = data.logs;
  document.getElementById("results-body").innerHTML = data.logs.length
    ? data.logs.map((log, index) => `<tr>
        <td>${escapeHtml(log["@timestamp"] || log.timestamp || "")}</td>
        <td>${escapeHtml(log.level || "")}</td>
        <td>${escapeHtml(log.service || "")}</td>
        <td>${escapeHtml(log.message || "")}</td>
        <td><button type="button" class="button button-secondary log-details" data-index="${index}">Détails</button></td>
      </tr>`).join("")
    : "<tr><td colspan=\"5\">Aucun log ne correspond.</td></tr>";

  document.querySelectorAll(".log-details").forEach(button => {
    button.addEventListener("click", () => {
      const log = window.currentLogs[Number(button.dataset.index)];
      document.getElementById("log-detail").textContent =
        JSON.stringify(log, null, 2);
      document.getElementById("log-dialog").showModal();
    });
  });
}

document.getElementById("search-button")?.addEventListener("click", () => runSearch(1));
document.getElementById("prev-page")?.addEventListener("click", () => runSearch(Math.max(searchPage - 1, 1)));
document.getElementById("next-page")?.addEventListener("click", () => runSearch(searchPage + 1));
document.getElementById("reset-button")?.addEventListener("click", () => {
  searchForm.reset();
  runSearch(1);
});
document.getElementById("close-log-dialog")?.addEventListener("click", () => {
  document.getElementById("log-dialog").close();
});
