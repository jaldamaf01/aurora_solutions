// webapp/frontend/js/app.js
import { EVENTS_CATALOG_URL, SELECTED_EVENT_KEY } from "./config.js";
import { track } from "./tracker.js";

async function loadCatalog() {
  const res = await fetch(EVENTS_CATALOG_URL, { cache: "no-store" });
  if (!res.ok) throw new Error(`No se pudo cargar catálogo: ${res.status}`);
  return await res.json();
}

function qs(name) {
  const url = new URL(window.location.href);
  return url.searchParams.get(name);
}

function money(v) {
  return new Intl.NumberFormat("es-ES", {
    style: "currency",
    currency: "EUR",
  }).format(v);
}

export async function renderEventsList(containerId = "events-container") {
  const container = document.getElementById(containerId);
  if (!container) return;

  const catalog = await loadCatalog();
  const events = catalog.events || [];

  // evento analítico: vista de listado
  track("view_event_list", { action: "view_list" });

  container.innerHTML = events
    .map(
      (e) => `
    <div class="card">
      <h3>${e.name}</h3>
      <p><b>Ciudad:</b> ${e.city} · <b>Categoría:</b> ${e.category}</p>
      <p><b>Fecha:</b> ${e.event_date} · <b>Precio base:</b> ${money(e.base_price)}</p>
      <a class="btn"
         href="./event_detail.html?id=${encodeURIComponent(e.event_id)}"
         data-track="open_event_detail"
         data-event-id="${e.event_id}">
         Ver detalle
      </a>
    </div>
  `,
    )
    .join("");
}

export async function renderEventDetail(containerId = "event-detail") {
  const container = document.getElementById(containerId);
  if (!container) return;

  const id = qs("id");
  if (!id) {
    container.innerHTML = `<p>Falta el parámetro <code>?id=</code>.</p>`;
    return;
  }

  const catalog = await loadCatalog();
  const events = catalog.events || [];
  const ev = events.find((x) => String(x.event_id) === String(id));

  if (!ev) {
    container.innerHTML = `<p>No existe el evento con id ${id} en el catálogo.</p>`;
    return;
  }

  // evento analítico: vista de detalle
  track("view_event_detail", {
    action: "view_detail",
    event_id: Number(ev.event_id),
  });

  container.innerHTML = `
    <div class="card">
      <h2>${ev.name}</h2>
      <p><b>Ciudad:</b> ${ev.city}</p>
      <p><b>Categoría:</b> ${ev.category}</p>
      <p><b>Fecha:</b> ${ev.event_date}</p>
      <p><b>Precio base:</b> ${money(ev.base_price)}</p>
      <p class="muted">${ev.description || ""}</p>

      <button class="btn"
              id="btn-checkout"
              data-track="begin_checkout"
              data-event-id="${ev.event_id}">
        Comprar entrada
      </button>
      <a class="link" href="./events.html" data-track="back_to_list">Volver al listado</a>
    </div>
  `;

  // Acción: comenzar checkout
  const btn = document.getElementById("btn-checkout");
  btn.addEventListener("click", () => {
    localStorage.setItem(SELECTED_EVENT_KEY, String(ev.event_id));
    track("begin_checkout", {
      action: "begin_checkout",
      event_id: Number(ev.event_id),
    });
    window.location.href = "./checkout.html";
  });
}

export async function renderCheckout(containerId = "checkout") {
  const container = document.getElementById(containerId);
  if (!container) return;

  const selectedId = localStorage.getItem(SELECTED_EVENT_KEY);
  if (!selectedId) {
    container.innerHTML = `<p>No hay evento seleccionado. Ve al <a href="./events.html">listado</a>.</p>`;
    return;
  }

  const catalog = await loadCatalog();
  const ev = (catalog.events || []).find(
    (x) => String(x.event_id) === String(selectedId),
  );

  if (!ev) {
    container.innerHTML = `<p>El evento seleccionado no existe en catálogo.</p>`;
    return;
  }

  container.innerHTML = `
    <div class="card">
      <h2>Checkout</h2>
      <p>Vas a comprar: <b>${ev.name}</b> (ID ${ev.event_id})</p>
      <p><b>Total:</b> ${money(ev.base_price)}</p>

      <button class="btn"
              id="btn-purchase"
              data-track="purchase_click"
              data-event-id="${ev.event_id}">
        Confirmar compra (simulada)
      </button>

      <p class="muted">
        Esta compra es simulada: generará un evento <code>purchase</code> en el clickstream.
      </p>
    </div>
  `;

  const btn = document.getElementById("btn-purchase");
  btn.addEventListener("click", async () => {
    // evento analítico: purchase
    await track("purchase", {
      action: "purchase",
      event_id: Number(ev.event_id),
      amount: Number(ev.base_price),
    });

    window.location.href = "./purchase_ok.html";
  });
}
