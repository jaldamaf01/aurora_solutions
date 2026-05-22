// webapp/frontend/js/tracker.js
import {
  STUDENT_ID,
  TRACK_ENDPOINT,
  SESSION_STORAGE_KEY,
  ATTR_STORAGE_KEY,
} from "./config.js";

function isoNow() {
  return new Date().toISOString();
}

function dtNow() {
  const d = new Date();
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

function randomId(prefix = "s") {
  return `${prefix}_${Math.random().toString(16).slice(2)}_${Date.now()}`;
}

export function getSessionId() {
  let sid = localStorage.getItem(SESSION_STORAGE_KEY);
  if (!sid) {
    sid = randomId("sess");
    localStorage.setItem(SESSION_STORAGE_KEY, sid);
  }
  return sid;
}

function getAttribution() {
  try {
    const raw = localStorage.getItem(ATTR_STORAGE_KEY);
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

function setAttribution(obj) {
  localStorage.setItem(ATTR_STORAGE_KEY, JSON.stringify(obj));
}

function captureUtmFromUrl() {
  const url = new URL(window.location.href);
  const utm_campaign = url.searchParams.get("utm_campaign");
  const referrer = document.referrer || null;

  // Guardamos la atribución si existe utm_campaign
  if (utm_campaign) {
    const current = getAttribution();
    setAttribution({
      ...current,
      utm_campaign,
      first_seen_ts: current.first_seen_ts || isoNow(),
      referrer: current.referrer || referrer,
    });
  } else {
    // Si no hay utm, al menos guardamos referrer si no estaba
    const current = getAttribution();
    if (!current.referrer && referrer) {
      setAttribution({ ...current, referrer });
    }
  }
}

async function postJson(url, payload) {
  const t0 = performance.now();
  try {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const t1 = performance.now();
    return { ok: res.ok, status: res.status, latency_ms: Math.round(t1 - t0) };
  } catch (e) {
    const t1 = performance.now();
    return {
      ok: false,
      status: 0,
      latency_ms: Math.round(t1 - t0),
      error: String(e),
    };
  }
}

/**
 * Envío de evento client-side al backend (/track).
 * Campos obligatorios del "contrato":
 * - student_id, timestamp, dt, session_id, event_type, source, page
 * + extras: action, element_id, utm_campaign, referrer, event_id...
 */
export async function track(event_type, data = {}) {
  const sid = getSessionId();
  const attr = getAttribution();

  const payload = {
    student_id: STUDENT_ID,
    timestamp: isoNow(),
    dt: dtNow(),
    session_id: sid,
    event_type,
    source: "client",
    page: window.location.pathname,
    referrer: attr.referrer || document.referrer || null,
    utm_campaign: attr.utm_campaign || null,
    ...data,
  };

  return await postJson(TRACK_ENDPOINT, payload);
}

// Auto: captura UTM al cargar
captureUtmFromUrl();

// Auto: page_view al cargar DOM
document.addEventListener("DOMContentLoaded", () => {
  track("page_view", { action: "load" });

  // Delegación de clicks con data-track
  document.body.addEventListener("click", (ev) => {
    const el = ev.target.closest("[data-track]");
    if (!el) return;

    const action = el.getAttribute("data-track") || "click";
    const element_id =
      el.id || el.getAttribute("data-id") || el.getAttribute("name") || null;
    const event_id = el.getAttribute("data-event-id") || null;

    track("click", {
      action,
      element_id,
      event_id: event_id ? Number(event_id) : null,
    });
  });
});
