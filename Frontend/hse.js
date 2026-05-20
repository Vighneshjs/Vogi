const form = document.querySelector("#inspectionForm");
const input = document.querySelector("#imageInput");
const previewGrid = document.querySelector("#previewGrid");
const inspectButton = document.querySelector("#inspectButton");
const clearButton = document.querySelector("#clearButton");
const resultBadge = document.querySelector("#resultBadge");
const summaryCards = document.querySelectorAll("#summaryCards strong");
const violationsList = document.querySelector("#violationsList");
const actionsList = document.querySelector("#actionsList");
const observationsText = document.querySelector("#observationsText");
const rawJson = document.querySelector("#rawJson");

function renderList(element, items) {
  element.innerHTML = "";
  for (const item of Array.isArray(items) && items.length ? items : ["None reported"]) {
    const li = document.createElement("li");
    li.textContent = item;
    element.append(li);
  }
}

function renderPreviews() {
  previewGrid.innerHTML = "";
  for (const file of Array.from(input.files)) {
    const card = document.createElement("article");
    const image = document.createElement("img");
    image.src = URL.createObjectURL(file);
    image.alt = file.name;
    image.onload = () => URL.revokeObjectURL(image.src);
    const label = document.createElement("span");
    label.textContent = file.name;
    card.append(image, label);
    previewGrid.append(card);
  }
}

function renderResult(payload) {
  const inspection = payload.inspection ?? {};
  const status = inspection.inspection_status ?? "UNKNOWN";
  resultBadge.textContent = status;
  summaryCards[0].textContent = status;
  summaryCards[1].textContent = inspection.severity_level ?? "UNKNOWN";
  summaryCards[2].textContent = inspection.critical_threat_detected ? "Yes" : "No";
  renderList(violationsList, inspection.detected_violations);
  renderList(actionsList, inspection.immediate_corrective_actions);
  observationsText.textContent = inspection.observations ?? "No observations returned.";
  rawJson.textContent = JSON.stringify(inspection, null, 2);
}

function renderError(message) {
  resultBadge.textContent = "Error";
  observationsText.textContent = message;
  renderList(violationsList, ["Inspection request failed."]);
  renderList(actionsList, ["Confirm the configured vision model is available."]);
  rawJson.textContent = JSON.stringify({ error: message }, null, 2);
}

input.addEventListener("change", renderPreviews);
clearButton.addEventListener("click", () => {
  form.reset();
  previewGrid.innerHTML = "";
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!input.files.length) {
    renderError("Upload at least one image before running inspection.");
    return;
  }
  inspectButton.disabled = true;
  inspectButton.textContent = "Inspecting...";
  try {
    const body = new FormData();
    for (const file of input.files) body.append("images", file);
    const response = await fetch("/api/inspect", { method: "POST", body });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error ?? data.detail ?? "Inspection failed.");
    renderResult(data);
  } catch (error) {
    renderError(error.message);
  } finally {
    inspectButton.disabled = false;
    inspectButton.textContent = "Run Inspection";
  }
});

